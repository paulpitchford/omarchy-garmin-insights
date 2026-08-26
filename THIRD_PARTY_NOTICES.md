# Third-party notices

## uv

This project directly uses [uv](https://github.com/astral-sh/uv) to create and run the locked Python environment. uv is distributed under the Apache License 2.0 or the MIT License, at the user's option.

uv is an external prerequisite and is not copied into this repository. Its upstream [licensing files](https://github.com/astral-sh/uv#license) contain the authoritative licence text.

## python-garminconnect

This project directly uses [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) 0.3.11, distributed under the MIT License.

Copyright (c) 2020-2026 Ron Klinkien.

The package is installed from PyPI and is not copied into this repository. Its upstream [LICENSE](https://github.com/cyberjunky/python-garminconnect/blob/0.3.11/LICENSE) file contains the authoritative licence text.

Transitive runtime packages are resolved and hash-pinned in `uv.lock`. Their installed package metadata and upstream licence files remain the authoritative notices for those packages. Development tools are also resolved through the lockfile and are not redistributed by this repository.
