import random
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from deap import algorithms, base, creator, tools

from akkudoktoreos.class_akku import PVAkku
from akkudoktoreos.class_ems import EnergieManagementSystem
from akkudoktoreos.class_haushaltsgeraet import Haushaltsgeraet
from akkudoktoreos.class_inverter import Wechselrichter
from akkudoktoreos.config import possible_ev_charge_currents
from akkudoktoreos.visualize import visualisiere_ergebnisse


class optimization_problem:
    def __init__(
        self,
        prediction_hours: int = 48,
        strafe: float = 10,
        optimization_hours: int = 24,
        verbose: bool = False,
        fixed_seed: Optional[int] = None,
    ):
        """Initialize the optimization problem with the required parameters."""
        self.prediction_hours = prediction_hours
        self.strafe = strafe
        self.opti_param = None
        self.fixed_eauto_hours = prediction_hours - optimization_hours
        self.possible_charge_values = possible_ev_charge_currents
        self.verbose = verbose
        self.fix_seed = fixed_seed
        self.optimize_ev = True

        # Set a fixed seed for random operations if provided
        if fixed_seed is not None:
            random.seed(fixed_seed)

    def split_charge_discharge(self, discharge_hours_bin: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Split the input array `discharge_hours_bin` into two separate arrays:
        - `charge`: Contains only the negative values from `discharge_hours_bin` (charging values).
        - `discharge`: Contains only the positive values from `discharge_hours_bin` (discharging values).
        
        Parameters:
        - discharge_hours_bin (np.ndarray): Input array with both positive and negative values.
        
        Returns:
        - charge (np.ndarray): Array with negative values from `discharge_hours_bin`, other values set to 0.
        - discharge (np.ndarray): Array with positive values from `discharge_hours_bin`, other values set to 0.
        """
        # Convert the input list to a NumPy array, if it's not already
        discharge_hours_bin = np.array(discharge_hours_bin)
        
        # Create charge array: Keep only negative values, set the rest to 0
        charge = -np.where(discharge_hours_bin < 0, discharge_hours_bin, 0)
        charge = charge / np.max(charge)

        # Create discharge array: Keep only positive values, set the rest to 0
        discharge = np.where(discharge_hours_bin > 0, discharge_hours_bin, 0)

        return charge, discharge
    
    # Custom mutation function that applies type-specific mutations
    def mutate(self,individual):
        # Mutate the discharge state genes (-1, 0, 1)
        individual[:self.prediction_hours], = self.toolbox.mutate_discharge(
            individual[:self.prediction_hours]
        )

        if self.optimize_ev:
            # Mutate the EV charging indices
            ev_charge_part = individual[self.prediction_hours : self.prediction_hours * 2]
            ev_charge_part_mutated, = self.toolbox.mutate_ev_charge_index(ev_charge_part)
            ev_charge_part_mutated[self.prediction_hours - self.fixed_eauto_hours :] = [0] * self.fixed_eauto_hours
            individual[self.prediction_hours : self.prediction_hours * 2] = ev_charge_part_mutated

        # Mutate the appliance start hour if present
        if self.opti_param["haushaltsgeraete"] > 0:
            appliance_part = [individual[-1]]
            appliance_part_mutated, = self.toolbox.mutate_hour(appliance_part)
            individual[-1] = appliance_part_mutated[0]

        return (individual,)

    # Method to create an individual based on the conditions
    def create_individual(self):
        # Start with discharge states for the individual
        individual_components = [self.toolbox.attr_discharge_state() for _ in range(self.prediction_hours)]

        # Add EV charge index values if optimize_ev is True
        if self.optimize_ev:
            individual_components += [self.toolbox.attr_ev_charge_index() for _ in range(self.prediction_hours)]

        # Add the start time of the household appliance if it's being optimized
        if self.opti_param["haushaltsgeraete"] > 0:
            individual_components += [self.toolbox.attr_int()]

        return creator.Individual(individual_components)

    def split_individual(
        self, individual: List[float]
    ) -> Tuple[List[int], List[float], Optional[int]]:
        """
        Split the individual solution into its components:
        1. Discharge hours (-1 (Charge),0 (Nothing),1 (Discharge)),
        2. Electric vehicle charge hours (possible_charge_values),
        3. Dishwasher start time (integer if applicable).
        """
        discharge_hours_bin = individual[: self.prediction_hours]
        eautocharge_hours_float = individual[self.prediction_hours : self.prediction_hours * 2]
        spuelstart_int = (
            individual[-1]
            if self.opti_param and self.opti_param.get("haushaltsgeraete", 0) > 0
            else None
        )
        return discharge_hours_bin, eautocharge_hours_float, spuelstart_int

    def setup_deap_environment(self, opti_param: Dict[str, Any], start_hour: int) -> None:
        """
        Set up the DEAP environment with fitness and individual creation rules.
        """
        self.opti_param = opti_param

        # Remove existing FitnessMin and Individual classes from creator if present
        for attr in ["FitnessMin", "Individual"]:
            if attr in creator.__dict__:
                del creator.__dict__[attr]

        # Create new FitnessMin and Individual classes
        creator.create("FitnessMin", base.Fitness, weights=(-1.0,))
        creator.create("Individual", list, fitness=creator.FitnessMin)

        # Initialize toolbox with attributes and operations
        self.toolbox = base.Toolbox()
        self.toolbox.register("attr_discharge_state", random.randint, -5, 1)
        if self.optimize_ev:
            self.toolbox.register("attr_ev_charge_index", random.randint, 0, len(possible_ev_charge_currents) - 1)
        self.toolbox.register("attr_int", random.randint, start_hour, 23)



        # Register individual creation function
        self.toolbox.register("individual", self.create_individual)

        # Register population, mating, mutation, and selection functions
        self.toolbox.register("population", tools.initRepeat, list, self.toolbox.individual)
        self.toolbox.register("mate", tools.cxTwoPoint)
        #self.toolbox.register("mutate", tools.mutFlipBit, indpb=0.1)
        # Register separate mutation functions for each type of value:
        # - Discharge state mutation (-5, 0, 1)
        self.toolbox.register("mutate_discharge", tools.mutUniformInt, low=-5, up=1, indpb=0.1)
        # - Float mutation for EV charging values
        self.toolbox.register("mutate_ev_charge_index", tools.mutUniformInt, low=0, up=len(possible_ev_charge_currents) - 1, indpb=0.1)
        # - Start hour mutation for household devices
        self.toolbox.register("mutate_hour", tools.mutUniformInt, low=start_hour, up=23, indpb=0.1)

        # Register custom mutation function
        self.toolbox.register("mutate", self.mutate)

        self.toolbox.register("select", tools.selTournament, tournsize=3)

    def evaluate_inner(
        self, individual: List[float], ems: EnergieManagementSystem, start_hour: int
    ) -> Dict[str, Any]:
        """
        Internal evaluation function that simulates the energy management system (EMS)
        using the provided individual solution.
        """
        ems.reset()
        discharge_hours_bin, eautocharge_hours_index, spuelstart_int = self.split_individual(
            individual
        )
        if self.opti_param.get("haushaltsgeraete", 0) > 0:
            ems.set_haushaltsgeraet_start(spuelstart_int, global_start_hour=start_hour)

        charge, discharge = self.split_charge_discharge(discharge_hours_bin)


        ems.set_akku_discharge_hours(discharge)
        ems.set_akku_charge_hours(charge)

        if self.optimize_ev:
            eautocharge_hours_float = [
                possible_ev_charge_currents[i] for i in eautocharge_hours_index
            ]            
            ems.set_eauto_charge_hours(eautocharge_hours_float)
        
        return ems.simuliere(start_hour)

    def evaluate(
        self,
        individual: List[float],
        ems: EnergieManagementSystem,
        parameter: Dict[str, Any],
        start_hour: int,
        worst_case: bool,
    ) -> Tuple[float]:
        """
        Evaluate the fitness of an individual solution based on the simulation results.
        """
        try:
            o = self.evaluate_inner(individual, ems, start_hour)
        except Exception as e:
            return (100000.0,)  # Return a high penalty in case of an exception
        
        gesamtbilanz = o["Gesamtbilanz_Euro"] * (-1.0 if worst_case else 1.0)
        
        discharge_hours_bin, eautocharge_hours_float, _ = self.split_individual(individual)

        # Small Penalty for not discharging
        gesamtbilanz += sum(
            0.01 for i in range(self.prediction_hours) if discharge_hours_bin[i] == 0.0
        )
        
        # Penalty for charging the electric vehicle during restricted hours
        # gesamtbilanz += sum(
        #     self.strafe
        #     for i in range(self.prediction_hours - self.fixed_eauto_hours, self.prediction_hours)
        #     if eautocharge_hours_float[i] != 0.0
        # )

        # Penalty for not meeting the minimum SOC (State of Charge) requirement
        if parameter["eauto_min_soc"] - ems.eauto.ladezustand_in_prozent() <= 0.0:
            gesamtbilanz += sum(
                self.strafe for ladeleistung in eautocharge_hours_float if ladeleistung != 0.0
            )

        individual.extra_data = (
            o["Gesamtbilanz_Euro"],
            o["Gesamt_Verluste"],
            parameter["eauto_min_soc"] - ems.eauto.ladezustand_in_prozent(),
        )

        # Adjust total balance with battery value and penalties for unmet SOC
        restwert_akku = ems.akku.aktueller_energieinhalt() * parameter["preis_euro_pro_wh_akku"]
        gesamtbilanz += (
            max(
                0,
                (parameter["eauto_min_soc"] - ems.eauto.ladezustand_in_prozent()) * self.strafe,
            )
            - restwert_akku
        )

        return (gesamtbilanz,)

    def optimize(
        self, start_solution: Optional[List[float]] = None, ngen: int = 400
    ) -> Tuple[Any, Dict[str, List[Any]]]:
        """Run the optimization process using a genetic algorithm."""
        population = self.toolbox.population(n=300)
        hof = tools.HallOfFame(1)
        stats = tools.Statistics(lambda ind: ind.fitness.values)
        stats.register("min", np.min)

        if self.verbose:
            print("Start optimize:", start_solution)

        # Insert the start solution into the population if provided
        if start_solution not in [None, -1]:
            for _ in range(3):
                population.insert(0, creator.Individual(start_solution))

        #Run the evolutionary algorithm
        algorithms.eaMuPlusLambda(
            population,
            self.toolbox,
            mu=100,
            lambda_=150,
            cxpb=0.5,
            mutpb=0.5,
            ngen=ngen,
            stats=stats,
            halloffame=hof,
            verbose=self.verbose,
        )

        member = {"bilanz": [], "verluste": [], "nebenbedingung": []}
        for ind in population:
            if hasattr(ind, "extra_data"):
                extra_value1, extra_value2, extra_value3 = ind.extra_data
                member["bilanz"].append(extra_value1)
                member["verluste"].append(extra_value2)
                member["nebenbedingung"].append(extra_value3)

        return hof[0], member

    def optimierung_ems(
        self,
        parameter: Optional[Dict[str, Any]] = None,
        start_hour: Optional[int] = None,
        worst_case: bool = False,
        startdate: Optional[Any] = None,  # startdate is not used!
        *,
        ngen: int = 400,
    ) -> Dict[str, Any]:
        """
        Perform EMS (Energy Management System) optimization and visualize results.
        """
        einspeiseverguetung_euro_pro_wh = np.full(
            self.prediction_hours, parameter["einspeiseverguetung_euro_pro_wh"]
        )

        # Initialize PV and EV batteries
        akku = PVAkku(
            kapazitaet_wh=parameter["pv_akku_cap"],
            hours=self.prediction_hours,
            start_soc_prozent=parameter["pv_soc"],
            min_soc_prozent=parameter["min_soc_prozent"],
            max_ladeleistung_w=5000,
        )
        akku.set_charge_per_hour(np.full(self.prediction_hours, 1))

        self.optimize_ev = True
        if parameter["eauto_min_soc"] - parameter["eauto_soc"] <0:
            self.optimize_ev = False

        eauto = PVAkku(
            kapazitaet_wh=parameter["eauto_cap"],
            hours=self.prediction_hours,
            lade_effizienz=parameter["eauto_charge_efficiency"],
            entlade_effizienz=1.0,
            max_ladeleistung_w=parameter["eauto_charge_power"],
            start_soc_prozent=parameter["eauto_soc"],
        )
        eauto.set_charge_per_hour(np.full(self.prediction_hours, 1))

        # Initialize household appliance if applicable
        spuelmaschine = (
            Haushaltsgeraet(
                hours=self.prediction_hours,
                verbrauch_wh=parameter["haushaltsgeraet_wh"],
                dauer_h=parameter["haushaltsgeraet_dauer"],
            )
            if parameter["haushaltsgeraet_dauer"] > 0
            else None
        )

        # Initialize the inverter and energy management system
        wr = Wechselrichter(10000, akku)
        ems = EnergieManagementSystem(
            gesamtlast=parameter["gesamtlast"],
            pv_prognose_wh=parameter["pv_forecast"],
            strompreis_euro_pro_wh=parameter["strompreis_euro_pro_wh"],
            einspeiseverguetung_euro_pro_wh=einspeiseverguetung_euro_pro_wh,
            eauto=eauto,
            haushaltsgeraet=spuelmaschine,
            wechselrichter=wr,
        )

        # Setup the DEAP environment and optimization process
        self.setup_deap_environment({"haushaltsgeraete": 1 if spuelmaschine else 0}, start_hour)
        self.toolbox.register(
            "evaluate",
            lambda ind: self.evaluate(ind, ems, parameter, start_hour, worst_case),
        )
        start_solution, extra_data = self.optimize(parameter["start_solution"], ngen=ngen)

        # Perform final evaluation on the best solution
        o = self.evaluate_inner(start_solution, ems, start_hour)
        discharge_hours_bin, eautocharge_hours_float, spuelstart_int = self.split_individual(
            start_solution
        )

        # Visualize the results
        visualisiere_ergebnisse(
            parameter["gesamtlast"],
            parameter["pv_forecast"],
            parameter["strompreis_euro_pro_wh"],
            o,
            discharge_hours_bin,
            eautocharge_hours_float,
            parameter["temperature_forecast"],
            start_hour,
            self.prediction_hours,
            einspeiseverguetung_euro_pro_wh,
            extra_data=extra_data,
        )

        # List output keys where the first element needs to be changed to None
        keys_to_modify = [
            "Last_Wh_pro_Stunde",
            "Netzeinspeisung_Wh_pro_Stunde",
            "akku_soc_pro_stunde",
            "Netzbezug_Wh_pro_Stunde",
            "Kosten_Euro_pro_Stunde",
            "Einnahmen_Euro_pro_Stunde",
            "E-Auto_SoC_pro_Stunde",
            "Verluste_Pro_Stunde",
            "Haushaltsgeraet_wh_pro_stunde",
        ]

        # Loop through each key in the list
        for key in keys_to_modify:
            # Convert the NumPy array to a list
            element_list = o[key].tolist()

            # Change the first value to None
            element_list[0] = None
            # Change the NaN to None (JSON)
            element_list = [
                None if isinstance(x, (int, float)) and np.isnan(x) else x for x in element_list
            ]

            # Assign the modified list back to the dictionary
            o[key] = element_list

        # Return final results as a dictionary
        return {
            "discharge_hours_bin": discharge_hours_bin,
            "eautocharge_hours_float": eautocharge_hours_float,
            "result": o,
            "eauto_obj": ems.eauto.to_dict(),
            "start_solution": start_solution,
            "spuelstart": spuelstart_int,
            "simulation_data": o,
        }

