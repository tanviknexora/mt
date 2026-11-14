
# ============================================================
# 1. IMPORTS & CONFIGURATION
# ============================================================

import pandas as pd
import numpy as np

FILE_PATH = r"C:\Users\Administrator\Downloads\trading-customers (18).csv"

COLUMNS = [
    'Client ID',
    'Real-Time Status',
    'Manager',
    'Assigned To',
    'Last Transaction',
    'Last Call'
]

DT_FORMAT = 'ISO8601'

PRIORITY_MAPPING = {
    'Active': 'P1',
    'Inactive': 'P2',
    'Sleeping': 'P3',
    'Stale': 'P3',
    'Lost Lead': 'P4',
    'Dormant': 'P4'
}


# ============================================================
# 2. DATA LOADING & PREPARATION
# ============================================================

def load_data(file_path):
    customer = pd.read_csv(file_path)
    df = customer.loc[:, COLUMNS].copy()
    return df


# ============================================================
# 3. DATE CALCULATIONS
# ============================================================

def difference(df, column, today):
    df[column] = pd.to_datetime(
        df[column],
        format=DT_FORMAT,
        utc=True,
        errors='coerce'
    )

    df[f'{column}_from_today'] = (
        today - df[column].dt.normalize()
    ).dt.days

    return df


def prepare_dates(df):
    today = pd.Timestamp.now(tz='UTC').normalize()

    for column in ['Last Transaction', 'Last Call']:
        df = difference(df, column, today)

    return df


# ============================================================
# 4. CUSTOMER FILTERING & PRIORITY ASSIGNMENT
# ============================================================

def filter_customers(df):
    req = df[
        ~(
            (df['Last Transaction_from_today'] < 2) |
            (df['Last Call_from_today'] < 2)
        )
    ].copy()

    req['Priority'] = (
        req['Real-Time Status']
        .map(PRIORITY_MAPPING)
        .fillna('Unassigned')
    )

    return req


# ============================================================
# 5. SUMMARY GENERATION
# ============================================================

def priority_summary(df, priority, group_col, days=None):

    filtered = df[df['Priority'] == priority]

    if days is not None:
        filtered = filtered[
            filtered['Last Call_from_today'] > days
        ]

    summary = (
        filtered.groupby(group_col, dropna=False)
        .size()
        .reset_index(name=f'{priority} Cases')
    )

    total = pd.DataFrame({
        group_col: ['Total'],
        f'{priority} Cases': [
            summary[f'{priority} Cases'].sum()
        ]
    })

    return pd.concat([summary, total], ignore_index=True)


# ============================================================
# 6. MAIN EXECUTION
# ============================================================

def main():

    # Load data
    df = load_data(FILE_PATH)

    # Calculate date differences
    df = prepare_dates(df)

    # Filter and assign priorities
    req = filter_customers(df)

    # Generate summaries
    summaries = {}

    for priority in ['P1', 'P2', 'P3', 'P4']:

        # P1 has no additional Last Call filter
        # P2, P3 and P4 require Last Call > 4 days
        days = None if priority == 'P1' else 4

        summaries[f'{priority}_tl'] = priority_summary(
            req, priority, 'Manager', days
        )

        summaries[f'{priority}_cre'] = priority_summary(
            req, priority, 'Assigned To', days
        )

    return req, summaries


# ============================================================
# 7. RUN
# ============================================================

req, summaries = main()

# Access individual summaries
p1_tl = summaries['P1_tl']
p1_cre = summaries['P1_cre']

p2_tl = summaries['P2_tl']
p2_cre = summaries['P2_cre']

p3_tl = summaries['P3_tl']
p3_cre = summaries['P3_cre']

p4_tl = summaries['P4_tl']
p4_cre = summaries['P4_cre']
