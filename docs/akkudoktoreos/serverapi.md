% SPDX-License-Identifier: Apache-2.0

# Server API

```{eval-sh}
[ -n "${READTHEDOCS_VIRTUALENV_PATH}" ] && READTHEDOCS_PYTHON=${READTHEDOCS_VIRTUALENV_PATH}/bin/python || true
${READTHEDOCS_PYTHON} ${READTHEDOCS_REPOSITORY_PATH:-.}/scripts/generate_openapi_md.py | ${READTHEDOCS_PYTHON} ${READTHEDOCS_REPOSITORY_PATH:-.}/scripts/extract_markdown.py --input-stdin --start-line "**Version**:"
```
