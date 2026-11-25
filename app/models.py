from sqlalchemy import Column, DateTime, Double, MetaData, Table, Text

metadata = MetaData()

readings = Table(
    "readings",
    metadata,
    Column("sensor_id", Text, primary_key=True),
    Column("metric", Text, primary_key=True),
    Column("ts", DateTime(timezone=True), primary_key=True),
    Column("value", Double, nullable=False),
)
