"""Validate frozen input schemas, coverage, and source identities before reproduction."""
from pathlib import Path
import hashlib
import json
import re
import pandas as pd
import numpy as np

BASE = Path(__file__).resolve().parent
INPUT = BASE / "input"
BASELINE = json.loads((BASE / "regression_baseline.json").read_text(encoding="utf-8"))
EXPECTED = {
    "prices.csv": {"date", "contract", "open", "high", "low", "close"},
    "all_contracts.csv": {"date", "contract", "open", "high", "low", "close"},
    "contract_inventory.csv": {"contract", "first_observed_date", "last_observed_date", "official_rows"},
    "institutional.csv": {"日期", "商品名稱", "身份別", "多方交易口數", "空方交易口數", "多空交易口數淨額"},
}

def validate(base=BASE, enforce_hash=True):
    base = Path(base)
    manifest = json.loads((base / "input_manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["inputs"]) == set(EXPECTED) == set(BASELINE["input_sha256"])
    frames = {}
    for filename, columns in EXPECTED.items():
        path = base / "input" / filename
        digest = hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        if enforce_hash:
            assert digest == manifest["inputs"][filename]["sha256"] == BASELINE["input_sha256"][filename], filename
        frame = pd.read_csv(path)
        assert columns.issubset(frame.columns), f"{filename}: missing schema columns"
        assert len(frame), f"{filename}: empty"
        required_values = columns - ({"open", "high", "low", "close"} if filename == "all_contracts.csv" else set())
        assert not frame[list(required_values)].isna().any().any(), f"{filename}: required nulls"
        frames[filename] = frame
    prices = frames["prices.csv"]
    contracts = frames["all_contracts.csv"]
    inv = frames["contract_inventory.csv"]
    inst = frames["institutional.csv"]
    for name, frame in [("prices", prices), ("all_contracts", contracts)]:
        assert not frame.duplicated(["date", "contract"]).any(), f"{name}: duplicate contract/day"
        for col in ["open", "high", "low", "close"]:
            assert ((frame[col].dropna() > 0) & np.isfinite(frame[col].dropna())).all(), f"{name}: invalid {col}"
            if name == "prices":
                assert frame[col].notna().all()
        complete = frame.dropna(subset=["open", "high", "low", "close"])
        assert (complete.high >= complete[["open", "close", "low"]].max(axis=1)).all()
        assert (complete.low <= complete[["open", "close"]].min(axis=1)).all()
        assert frame.contract.astype(str).str.fullmatch(r"TX\d{6}").all()
    assert not prices.duplicated("date").any()
    assert prices.date.is_monotonic_increasing
    assert (pd.to_datetime(prices.date) <= pd.Timestamp(BASELINE["period"][1])).all()
    assert pd.Timestamp(BASELINE["period"][0]) in set(pd.to_datetime(prices.date))
    assert pd.Timestamp(BASELINE["period"][1]) in set(pd.to_datetime(prices.date))
    keys = contracts.set_index(["date", "contract"])
    assert set(map(tuple, prices[["date", "contract"]].itertuples(index=False, name=None))).issubset(keys.index)
    assert not inv.duplicated("contract").any()
    assert inv.contract.astype(str).str.fullmatch(r"TX\d{6}").all()
    assert set(prices.contract).issubset(set(inv.contract))
    dates = pd.to_datetime(inst["日期"])
    assert not inst.assign(date=dates).duplicated(["date", "身份別"]).any()
    assert (inst.groupby("日期").size() == 3).all()
    assert (inst["多方交易口數"] - inst["空方交易口數"] == inst["多空交易口數淨額"]).all()
    assert (inst[["多方交易口數", "空方交易口數"]] >= 0).all().all()
    assert set(pd.to_datetime(prices.loc[pd.to_datetime(prices.date) >= pd.Timestamp(BASELINE['period'][0])].date)).issubset(set(dates))
    coverage = {}
    for filename, frame in frames.items():
        field = "日期" if filename == "institutional.csv" else ("first_observed_date" if filename == "contract_inventory.csv" else "date")
        coverage[filename] = dict(rows=len(frame), first=str(pd.to_datetime(frame[field]).min().date()),
                                  last=str(pd.to_datetime(frame["last_observed_date"] if filename == "contract_inventory.csv" else frame[field]).max().date()))
        assert coverage[filename] == manifest["inputs"][filename]["coverage"], filename
    return coverage

if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, indent=2))
