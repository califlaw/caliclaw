import shutil
import subprocess
from pathlib import Path

from setuptools import setup
from Cython.Build import cythonize

setup(
    name="caliclaw_engine",
    ext_modules=cythonize(
        "bin/_engine.pyx",
        compiler_directives={"language_level": "3"},
    ),
    script_args=["build_ext", "--build-lib", "bin"],
)

strip = shutil.which("strip")
if strip:
    for so in Path("bin").glob("_engine*.so"):
        subprocess.run([strip, str(so)], check=False)
