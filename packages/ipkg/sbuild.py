import os
import shutil
from pathlib import Path


source = Path(os.environ["SMART_BUILD_SOURCE_DIR"])
stage = Path(os.environ["SMART_BUILD_STAGE_DIR"])
install_path = os.environ.get("SMART_BUILD_INSTALL_PATH", "/usr/bin/ipkg")
destination = stage.joinpath(*Path(install_path.lstrip("/")).parts)
destination.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(source / "ipkg.sh", destination)
destination.chmod(0o755)
