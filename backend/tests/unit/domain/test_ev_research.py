"""Research for electric facts (spec 006 FR-009, R10): extra queries and the energy-input minimum."""

from automind.domain import research_plan, search_plan
from automind.domain.search_plan import Identity, PlannedQuery

CAR = Identity("BYD", "Seal U", None, "DM-i 1.5 Boost")
TPL = {"specs_ev": "{short} autonomía kWh {sites}", "specs_cs": "{short} batería descargada {sites}",
       "specs_ev@EN": "{short} range kWh {sites}"}  # fmt: skip
BASE = [PlannedQuery("BYD Seal U ficha técnica site:km77.com", "FAVOURITE", "specs", "ES", ("km77.com",)),
        PlannedQuery("BYD Seal U ficha técnica site:x.es", "FAVOURITE", "specs", "ES", ("x.es",))]  # fmt: skip


def test_plug_in_gets_electric_and_empty_battery_queries_once():
    out = search_plan.ev_queries(BASE, CAR, "PHEV", TPL)
    assert [q.text.split(" site:")[0].split()[-2:] for q in out] == [["autonomía", "kWh"], ["batería", "descargada"]]
    assert all(q.sites == ("km77.com",) and q.kind == "FAVOURITE" for q in out)


def test_bev_gets_no_empty_battery_query_and_combustion_none():
    assert len(search_plan.ev_queries(BASE, CAR, "BEV", TPL)) == 1
    assert search_plan.ev_queries(BASE, CAR, "ICE", TPL) == []
    assert search_plan.ev_queries(BASE, CAR, "HEV", TPL) == []


def test_energy_inputs_missing():
    assert research_plan.energy_inputs_missing("PHEV", {"battery_kwh", "range_wltp"}) == ["consumption_cs"]
    assert research_plan.energy_inputs_missing("PHEV", {"consumption_cs", "consumption_ev", "range_real"}) == []
    assert research_plan.energy_inputs_missing("BEV", set()) == ["consumption"]
    assert research_plan.energy_inputs_missing("ICE", set()) == []
