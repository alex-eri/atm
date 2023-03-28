from setuptools import setup
from datetime import datetime

setup(
    name="ATM",
    version="1." + datetime.now().strftime('%Y.%m.%d-%H%M'),

    install_requires=[
          "aiohttp", "pyserial-asyncio", "toml"
    ],
    packages=['atm.sber', 'atm.cashcode', 'atm.lcdm2'],
    package_data={'atm.sber':['sb_pilot/*', 'demo/*'] },
    #include_package_data=True,
    #data_files=data_files,
    python_requires='>=3.6'
)

