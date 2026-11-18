# Third party components

The Windows x64 offline package contains the following upstream components.
The build checks each archive against its pinned SHA-256 before extraction.

| Component | Archive SHA-256 | Upstream download and digest | License file in the plugin |
| --- | --- | --- | --- |
| CPython 3.13.17 for Windows x64 | `9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38` | [Embeddable ZIP](https://www.python.org/ftp/python/3.13.17/python-3.13.17-embed-amd64.zip), [Sigstore bundle](https://www.python.org/ftp/python/3.13.17/python-3.13.17-embed-amd64.zip.sigstore) (`messageSignature.messageDigest` in Base64) | `runtime/LICENSE.txt` (Python Software Foundation License and bundled notices) |
| Cua Driver 0.53.0 for Windows x64 | `9dcf88dfdd9cd75613130d23ad25a9656ed1ecacc5e4bc7f24b763d788316243` | [Release ZIP](https://github.com/trycua/cua/releases/download/cua-driver-rs-v0.53.0/cua-driver-rs-0.53.0-windows-x86_64.zip), [SHA256SUMS](https://github.com/trycua/cua/releases/download/cua-driver-rs-v0.53.0/SHA256SUMS) | `app/vendor/cua/LICENSE` (MIT), `app/vendor/cua/THIRD_PARTY_NOTICES.md` |

The build adds `../app` to CPython's `python313._pth` so the embedded
interpreter can import the plugin modules. Every other CPython file comes
from the upstream archive unchanged.

The build copies the two Cua executables and their license notices unchanged
from the release. The plugin source in `app/driver_backend.py` pins the
individual executable digests.
