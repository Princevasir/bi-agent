import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://bi_readonly:readonly_dev_pw@localhost:5433/analytics",
)