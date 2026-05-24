from __future__ import annotations

from frw_api.adapters.alternative_signals import (
    FINRAShortInterestAdapter,
    FINRAShortVolumeAdapter,
    PentagonPizzaAdapter,
    PublicShortResearchAdapter,
    TrumpFilingsAdapter,
)
from frw_api.adapters.bls import BLSAdapter
from frw_api.adapters.ecb import ECBAdapter
from frw_api.adapters.eia import EIAAdapter
from frw_api.adapters.federal_reserve import FederalReserveCalendarAdapter
from frw_api.adapters.fred import FREDAdapter
from frw_api.adapters.gdelt import GDELTDiscoveryAdapter
from frw_api.adapters.sec import SECEdgarAdapter
from frw_api.adapters.worldbank import WorldBankAdapter


def adapter_registry():
    return {
        "bls": BLSAdapter(),
        "fred": FREDAdapter(),
        "federal_reserve": FederalReserveCalendarAdapter(),
        "sec_edgar": SECEdgarAdapter(),
        "eia": EIAAdapter(),
        "ecb": ECBAdapter(),
        "world_bank": WorldBankAdapter(),
        "gdelt": GDELTDiscoveryAdapter(),
        "finra_short_interest": FINRAShortInterestAdapter(),
        "finra_reg_sho_short_volume": FINRAShortVolumeAdapter(),
        "public_short_research": PublicShortResearchAdapter(),
        "pentagon_pizza": PentagonPizzaAdapter(),
        "trump_filings": TrumpFilingsAdapter(),
    }
