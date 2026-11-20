# Home Assistant 2026.10+ replaces voluptuous with probatio at import time
# (homeassistant/__init__.py: probatio.compat.install_as_voluptuous()), so at runtime
# `import voluptuous` is probatio. Type-check it as probatio too; HA's own signatures
# expect probatio types.
from probatio import *  # noqa: F401,F403
