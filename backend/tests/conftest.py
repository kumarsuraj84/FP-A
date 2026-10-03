import re
import pytest


class FakeOra:
    """Records every SQL statement; answers by simple pattern so no network is needed."""
    def __init__(self, ncols=36, total=1000, nulls=0, stats_rows=1000):
        self.calls, self.ncols, self.total, self.nulls, self.stats_rows = [], ncols, total, nulls, stats_rows

    def query(self, sql, params=None):
        self.calls.append((sql, params))
        s = " ".join(sql.split())
        if "FROM all_tab_columns" in s:
            return [{"COLUMN_NAME": f"COL{i}", "DATA_TYPE": "VARCHAR2", "DATA_LENGTH": 10, "DATA_PRECISION": None,
                     "DATA_SCALE": None, "NULLABLE": "Y"} for i in range(self.ncols)]
        if "FROM all_tables" in s:
            return [{"NUM_ROWS": self.stats_rows, "LAST_ANALYZED": None}]
        if "FETCH FIRST" in s and "COUNT(" not in s:
            return [{"COL0": "x"}]
        row = {"N": self.total, "DMIN": "2026-04-01", "DMAX": "2026-09-30", "DEBIT": 5, "CREDIT": 5, "D0": 7, "D1": 3}
        row.update({f"D{i}": 1 for i in range(2, 10)})
        for i in range(self.ncols):
            row[f"C{i}"] = self.total - self.nulls
        return [row]

    def count(self, pred):
        return sum(1 for sql, _ in self.calls if pred(" ".join(sql.split())))


@pytest.fixture
def fake():
    return FakeOra
