import qlib
from qlib.data import D

qlib.init(provider_uri="D:/qlib_data/cn_data")

df = D.features(
    instruments=["sh600000"],
    fields=["$close"],
    start_time="2020-01-01",
    end_time="2020-01-10",
)

print(df)
