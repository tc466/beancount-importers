"""Importer for sui.com (随手记) CSV files."""

import csv
import enum
from typing import Dict, Optional, Union

from beancount.core import data
from beancount.core import flags
from beancount.core import number
from beancount.core.amount import Amount
from beancount.ingest.importers import csv as beancount_csv
from beancount.ingest.importers.mixins import identifier
from beancount.utils.date_utils import parse_date_liberally


class Col(enum.Enum):
    """The set of interpretable columns."""

    # The type of the transaction.
    TYPE = '[TYPE]'

    # The settlement date, the date we should create the posting at.
    DATE = '[DATE]'

    # Category of the expense / income.
    CATEGORY = '[CATEGORY]'

    # Account names.
    ACCOUNT1 = '[ACCOUNT1]'
    ACCOUNT2 = '[ACCOUNT2]'

    # The amount being posted.
    AMOUNT = '[AMOUNT]'

    # The payee field.
    PAYEE = '[PAYEE]'

    # The narration field.
    NARRATION = '[NARRATION1]'


class SuiImporter(identifier.IdentifyMixin):
    """Importer for sui.com (随手记) CSV files."""

    TYPE_EXPENSE = '支出'
    TYPE_INCOME = '收入'
    TYPE_TRANSFER = '转账'
    TYPE_ASSET_ADJUSTMENT = '余额变更'
    TYPE_LIABILITY_ADJUSTMENT = '负债变更'
    TYPE_ACCOUNT_RECEIVABLE_ADJUSTMENT = '债权变更'

    def __init__(self,
                 accounts_map: Dict[str, str],
                 currency_map: Dict[str, str],
                 categories_map: Dict[str, str],
                 asset_adjustment_account: str,
                 liability_adjustment_account: str,
                 account_receivable_adjustment_account: str,
                 csv_dialect: Union[str, csv.Dialect] = 'excel',
                 debug: bool = False):
        """Constructor.
        
        Args:
          acccounts_map: A dictionary mapping sui.com account names to Beancount
            account names.
          currency_map: A dictionary mapping sui.com account names to its
            currency.
          categories_map: A dictionary mapping sui.com category names to
            Beancount expenses.
          asset_adjustment_account: Account on the other side of imported asset
            adjustment transactions.
          liability_adjustment_account: Account on the other side of imported
            liability adjustment transactions.
          account_receivable_adjustment_account: Account on the other side of
            imported account receivable adjustment transactions.
          csv_dialect: A `csv` dialect given either as string or as instance or
            subclass of `csv.Dialect`.
          debug: Whether or not to print debug information.
        """
        # Constructs the identifier mixin.
        super().__init__(matchers=[('mime', 'text/csv')])

        self.accounts_map = accounts_map
        self.currency_map = currency_map
        self.categories_map = categories_map
        self.asset_adjustment_account = asset_adjustment_account
        self.liability_adjustment_account = liability_adjustment_account
        self.account_receivable_adjustment_account = account_receivable_adjustment_account

        self.config = {
            Col.TYPE: '交易类型',
            Col.DATE: '日期',
            Col.ACCOUNT1: '账户1',
            Col.ACCOUNT2: '账户2',
            Col.AMOUNT: '金额',
            Col.CATEGORY: '子分类',
            Col.PAYEE: '商家',
            Col.NARRATION: '备注',
        }
        self.csv_dialect = csv_dialect
        self.debug = debug

    def extract(self, file, existing_entries=None):
        """Extracts transactions from file."""
        entries = []

        # Normalize the configuration to fetch by index.
        iconfig, has_header = beancount_csv.normalize_config(
            self.config, file.head(), self.csv_dialect)
        self.iconfig = iconfig

        reader = iter(csv.reader(open(file.name), dialect=self.csv_dialect))

        # Skip header, if one was detected.
        if has_header:
            next(reader)

        # Parse all the transactions.
        for index, row in enumerate(reader, 1):
            if not row:
                continue
            if row[0].startswith('#'):
                continue

            # If debugging, print out the rows.
            if self.debug:
                print(row)

            # Extract the data we need from the row, based on the configuration.
            type_ = self.get_type(row)
            date = self.get_date(row)
            payee = self.get_payee(row)
            narration = self.get_narration(row)

            # Create a transaction
            meta = data.new_metadata(file.name, index)
            tags = data.EMPTY_SET
            links = data.EMPTY_SET
            txn = data.Transaction(meta, date, self.FLAG, payee, narration,
                                   tags, links, [])

            # Attach postings to the transaction
            if type_ == self.TYPE_EXPENSE:
                self.extract_expense(txn, row)
            elif type_ in (self.TYPE_INCOME):
                self.extract_income(txn, row)
            elif type_ == self.TYPE_TRANSFER:
                self.extract_transfer(txn, row)
            elif type_ == self.TYPE_ASSET_ADJUSTMENT:
                self.extract_asset_adjustment(txn, row)
            elif type_ == self.TYPE_ACCOUNT_RECEIVABLE_ADJUSTMENT:
                self.extract_account_receivable_adjustment(txn, row)
            elif type_ == self.TYPE_LIABILITY_ADJUSTMENT:
                self.extract_liability_adjustment(txn, row)
            else:
                raise ValueError(f'Unknown transaction type: {type_}')

            # Add the transaction to the output list
            entries.append(txn)

        # Reverse the list because the CSV file is in descending order
        entries = list(reversed(entries))

        return entries

    def extract_expense(self, txn, row):
        """Extracts data from an expense row."""
        amount = self.get_amount(row)
        account, currency = self.get_beancount_account_and_currency(row)
        units = Amount(amount, currency)
        category = self.get_beancount_category(row)

        txn.postings.append(
            data.Posting(account, -units, None, None, None, None))
        txn.postings.append(
            data.Posting(category, units, None, None, None, None))

    def extract_income(self, txn, row):
        """Extracts data from an income row."""
        amount = self.get_amount(row)
        account, currency = self.get_beancount_account_and_currency(row)
        units = Amount(amount, currency)
        category = self.get_beancount_category(row)
        txn.postings.append(
            data.Posting(account, units, None, None, None, None))
        txn.postings.append(
            data.Posting(category, -units, None, None, None, None))

    def extract_transfer(self, txn, row):
        """Extracts data from a transfer row."""
        amount = self.get_amount(row)
        from_account, from_currency = self.get_beancount_account_and_currency(
            row)
        units = Amount(amount, from_currency)
        to_account, to_currency = self.get_beancount_account_and_currency(
            row, Col.ACCOUNT2)

        txn.postings.append(
            data.Posting(from_account, -units, None, None, None, None))
        if from_currency == to_currency:
            txn.postings.append(
                data.Posting(to_account, units, None, None, None, None))
        else:
            # In case `from_currency` is different from `to_currency`, the
            # amount in `to_currency` is missing in the CSV file. Leave amount
            # empty and mark the posting problematic.
            txn.postings.append(
                data.Posting(to_account, Amount(number.ZERO, to_currency), None,
                    None, flags.FLAG_WARNING, None))

    def extract_asset_adjustment(self, txn, row):
        """Extracts data from an asset adjustment row."""
        amount = self.get_amount(row)
        account, currency = self.get_beancount_account_and_currency(row)
        units = Amount(amount, currency)

        txn.postings.append(
            data.Posting(account, units, None, None, None, None))
        txn.postings.append(
            data.Posting(self.asset_adjustment_account, -units, None, None,
                None, None))

    def extract_account_receivable_adjustment(self, txn, row):
        """Extracts data from an account receivable adjustment row."""
        amount = self.get_amount(row)
        account, currency = self.get_beancount_account_and_currency(row)
        units = Amount(amount, currency)

        txn.postings.append(
            data.Posting(account, units, None, None, None, None))
        txn.postings.append(
            data.Posting(self.account_receivable_adjustment_account, -units,
                None, None, None, None))

    def extract_liability_adjustment(self, txn, row):
        amount = self.get_amount(row)
        account, currency = self.get_beancount_account_and_currency(row)
        units = Amount(amount, currency)

        txn.postings.append(
            data.Posting(account, -units, None, None, None, None))
        txn.postings.append(
            data.Posting(self.liability_adjustment_account, units, None, None,
                None, None))

    def get(self, row, field_type):
        """Returns a field from a CSV row."""
        if field_type in self.iconfig:
            return row[self.iconfig[field_type]]
        else:
            return None
    
    def get_type(self, row):
        """Parses the type from a CSV row."""
        return self.get(row, Col.TYPE)

    def get_date(self, row):
        """Parses the date from a CSV row."""
        return parse_date_liberally(self.get(row, Col.DATE))

    def get_payee(self, row):
        """Parses the payee from a CSV row."""
        payee = self.get(row, Col.PAYEE)
        return payee.strip() if payee else None

    def get_narration(self, row):
        """Parses the narration from a CSV row."""
        narration = self.get(row, Col.NARRATION)
        return narration.strip() if narration else None

    def get_amount(self, row):
        """Parses the amount from a CSV row."""
        amount = self.get(row, Col.AMOUNT)
        return number.D(amount) if amount else None
    
    def get_beancount_account_and_currency(self, row, field_type=Col.ACCOUNT1):
        """Returns the mapped Beancount account and currency from a CSV row."""
        account = self.get(row, field_type)
        return self.accounts_map[account], self.currency_map[account]
    
    def get_beancount_category(self, row):
        """Returns the mapped Beancount category from a CSV row."""
        category = self.get(row, Col.CATEGORY)
        return self.categories_map[category]
