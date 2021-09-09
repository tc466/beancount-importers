# Beancount importers

## sui.com (随手记)

### Usage

1. Export data as Excel file from https://www.sui.com
2. Convert Excel file to CSV files (one sheet per file)
3. Create a configuration file `sui.config.py`, example below:

```python
"""Config for importing data from sui.com."""

from importers.sui import sui

accounts_map = {
    'Chase Checking': 'Assets:Chase:Checking',
    'Chase Savings': 'Assets:Chase:Savings',
    '支付宝': 'Assets:Alipay:支付宝',
 }

currency_map = {
    'Chase Checking': 'USD',
    'Chase Savings': 'USD',
    '支付宝': 'CNY',
}

categories_map = {
    '早午晚餐': 'Expenses:Food:Meal',
    '食品杂货': 'Expenses:Food:Grocery', 
    '工资收入': 'Income:Employment:Salary',
}

asset_adjustment_account = 'Equity:AssetAdjustment'
liability_adjustment_account = 'Equity:LiabilityAdjustment'
account_receivable_adjustment_account = 'Equity:AccountReceivableAdjustment'

CONFIG = [
    sui.SuiImporter(accounts_map,
                    currency_map,
                    categories_map,
                    asset_adjustment_account,
                    liability_adjustment_account,
                    account_receivable_adjustment_account)
]
```

4. Run `bean-extract` to extract transactions to Beancount file:

```
PYTHONPATH=$PWD bean-extract sui.config.py *.csv >> output.beancount
```
