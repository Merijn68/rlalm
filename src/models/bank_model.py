# Bank Assets
import pandas as pd
import numpy as np
import datetime
from loguru import logger
from pandas.tseries.offsets import BDay
from pandas.tseries.offsets import DateOffset
from datetime import timedelta
from random import randrange
from dateutil.relativedelta import relativedelta
from src.models import predict
from src.visualization import visualize
from src.data import dataset
from src.data.zerocurve import Zerocurve
from src.data.interest import Interest
import math


class Bankmodel:
    """Cashflow model of a bank"""

    def __init__(self, pos_date: datetime):
        self.df_cashflows = pd.DataFrame()
        self.df_mortgages = pd.DataFrame()
        self.df_swaps = pd.DataFrame()
        self.pos_date = pos_date
        self.origin_pos_date = pos_date

    def _random_date_(self, start: datetime, end: datetime) -> datetime:
        """return a random business date between start and end date"""
        delta = end - start
        date = start + datetime.timedelta(days=randrange(delta.days))
        # shift dates to next business day if closed
        if date.weekday() >= 5:
            date = date + BDay(1)
            date = date.to_pydatetime()
        return date

    def _date_schedule_(
        self, start_date: str, n_periods: int, offset: str = "months"
    ) -> np.array:
        """Generate monthly payment dates schedule"""
        # create a date range with monthly frequency starting at start_date
        offset = offset.lower()
        if offset == "months":
            freq = DateOffset(months=1)
        else:
            freq = DateOffset(years=1)

        dates = pd.date_range(start=start_date, periods=n_periods, freq=freq)
        # shift dates to next business day if closed
        return dates.map(lambda x: x + BDay(1) if x.weekday() >= 5 else x)

    def _generate_mortgage_cashflow_(
        self, principal, interest_rate, years, fixed_period
    ):
        n = years * 12  # number of mortgage payments
        periods = fixed_period * 12
        principal_payment = round(principal / n)  # monthly principal payment
        r = interest_rate / 12  # monthly interest rate
        cashflow = []
        cashflow.append((0, -principal))
        for i in range(1, periods + 1):
            interest_paid = round(principal * r, 0)
            if i == periods:
                principal_payment = principal
            principal = principal - principal_payment
            cashflow.append((i, principal_payment + interest_paid))
        cashflow_df = pd.DataFrame(cashflow, columns=["period", "cashflow"])
        return cashflow_df

    def _generate_mortgage_cashflows_(self, contracts: pd.DataFrame) -> pd.DataFrame:
        mortgage_tenor = 30
        dfs = []
        for _, row in contracts.iterrows():
            df_cashflows = self._generate_mortgage_cashflow_(
                row.principal, row.interest / 100, mortgage_tenor, row.years
            )
            df_cashflows["value_dt"] = self._date_schedule_(
                row.start_date, len(df_cashflows), offset="months"
            )
            df_cashflows["contract"] = row.contract
            df_cashflows["type"] = "mortgage"
            dfs.append(df_cashflows)
        df_all = pd.concat([dfs[i] for i in range(len(contracts))], axis=0)
        return df_all

    def generate_mortgage_contracts(
        self, n: int, df_i: pd.DataFrame, amount: float = 100000
    ):
        """Generate a portfolio of mortgages"""
        # Generate mortgage portfolio of n mortgages, active at pos_date
        # probability of 10 years contracts is 10x higher then 1 year contract
        # as they can start 10 years before.
        # Devision in fixed interest period is dependend on the coupon rates
        category = np.random.choice(a=[0, 1, 2, 3], size=n, p=[0.03, 0.14, 0.23, 0.60])
        df = pd.DataFrame()
        df["category"] = category
        d = {0: "<= 1 year", 1: "1>5 years", 2: "5>10 years", 3: ">10 years"}
        df["fixed_period"] = df["category"].map(d).astype("category")
        df["fixed_period"].cat.set_categories(
            ["<= 1 year", "1>5 years", "5>10 years", ">10 years"], ordered=True
        )
        df["years"] = df["category"].map({0: 1, 1: 5, 2: 10, 3: 20})
        df["start_date"] = df.apply(
            lambda row: self._random_date_(
                self.pos_date - relativedelta(years=row.years), self.pos_date
            ),
            axis=1,
        )
        df["principal"] = amount
        df["period"] = (
            df["start_date"].to_numpy().astype("datetime64[M]")
        )  # trick to get 1th of the month
        df = df.merge(df_i.reset_index(), how="left", on=["period", "fixed_period"])
        df["interest"] = df["interest"].fillna(
            df_i["interest"].iloc[-1]
        )  # fill missing values with last coupon rate - not a nice solution
        df["contract"] = np.arange(len(df))  # assign a contract id

        self.df_mortgages = pd.concat([self.df_mortgages, df])
        logger.info(f"Added {len(df)} mortgages to our portfolio.")

        df_cashflows = self._generate_mortgage_cashflows_(df)
        self.df_cashflows = pd.concat([self.df_cashflows, df_cashflows])
        logger.info(f"Added {len(df_cashflows)} cashflows to our model.")

        return df
    
    def generate_swap_contract(
        self, buysell: str, tenor: int, zerocurve: Zerocurve, amount: float = 100000
    ):
        buysell = buysell.lower()        
        contract_no = len(self.df_swaps) + 1
        start_date = self.pos_date + BDay(2)        
        if buysell == 'buy':
            pay = 'fixed'
            pay_freq = 'annual'
            rec = 'float'
            rec_freq = 'semi annual'
        else:
            pay = 'float'
            pay_freq = 'semi annual'
            rec = 'fixed'
            rec_freq = 'annual'
        swap = pd.DataFrame( 
            [{ 
                'contract': contract_no,
                'pay': pay,
                'start_date': start_date,
                'pay_freq': pay_freq,
                'rec': rec,
                'rec_freq': rec_freq,
                'principal': amount,                        
                'tenor': tenor
            }]
        )
        self.df_swaps = pd.concat([self.df_swaps, swap])

    def generate_nonmaturing_deposits(
        self, principal: float = 1000000, core: float = 0.4, maturity: int = 54
    ) -> pd.DataFrame:
        """Generate Non Maturing Deposits (e.g. bank and saving accounts )"""
        self.nmd_pricipal = principal
        self.nmd_core = core
        self.nmd_maturity = maturity
        noncore = 1 - core
        cashflow = []
        # cashflow.append((0, +principal))
        cashflow.append((1, round(-principal * noncore)))
        cashflow.append((2, round(-principal * core)))
        df_cashflows = pd.DataFrame(cashflow, columns=["period", "cashflow"])
        df_cashflows["value_dt"] = [
            # self.pos_date,
            self.pos_date + BDay(1),
            self.pos_date + DateOffset(months=maturity),
        ]
        df_cashflows["type"] = "deposits"
        self.df_cashflows = pd.concat([self.df_cashflows, df_cashflows])
        return df_cashflows

    def step_nmd(self):
        self.df_cashflows = self.df_cashflows[self.df_cashflows["type"] != "deposits"]
        self.generate_nonmaturing_deposits(
            self.nmd_pricipal, self.nmd_core, self.nmd_maturity
        )

    def generate_funding(
        self, principal: float = 1000000, rate: float = 1, maturity: int = 120
    ) -> pd.DataFrame:
        """Generate Funding from capital market  )"""

        r = rate / 100
        interest_paid = round(-principal * r, 0)
        periods = int(round(maturity / 12, 0))
        principal_payment = 0
        cashflow = []
        for i in range(1, periods + 1):
            if i == periods:
                principal_payment = -round(principal)
            cashflow.append((i, principal_payment + interest_paid))
        df_cashflows = pd.DataFrame(cashflow, columns=["period", "cashflow"])
        df_cashflows["value_dt"] = self._date_schedule_(
            self.pos_date, len(df_cashflows), offset="years"
        )
        df_cashflows["type"] = "Funding"
        self.df_cashflows = pd.concat([self.df_cashflows, df_cashflows])
        return df_cashflows

    def reset(self):
        # Reset should reset to initial position - not just wipe them out...
        self.pos_date = self.origin_pos_date
        # self.df_cashflows = pd.DataFrame()
        # self.df_mortgages = pd.DataFrame()

    def calculate_npv(self, zerocurve: Zerocurve):
        """Calculate the NPV of the cashflows given the zero curve"""
        pos_date = self.pos_date
        df_forward = zerocurve.interpolate(pos_date)
        df = self.df_cashflows
        df_c = df[df["value_dt"] > self.pos_date]  # only include future cashflows
        df_npv = df_c.merge(df_forward, left_on="value_dt", right_on=df_forward.index)
        df_npv["pos_dt"] = pos_date
        df_npv["year_frac"] = round(
            (df_npv["value_dt"] - df_npv["pos_dt"]) / timedelta(365, 0, 0, 0), 5
        )
        df_npv["df"] = 1 / (1 + df_npv["rate"] / 100) ** df_npv["year_frac"]
        df_npv["npv"] = round(df_npv["cashflow"] * df_npv["df"], 2)
        return df_npv["npv"].sum()

    def calculate_nii(self, zerocurve: Zerocurve):
        # substraction of the interst expense - interest income
        # To calculate this correctly I need to extend the cashflow model
        # We need to seperate principal payments and interest payments
        pass

    def calculate_risk(
        self, zerocurve: Zerocurve, shock: int = 1, direction: str = "parallel"
    ):
        """Calculate a parallel shift, short shift or long shift in the zero curve"""
        pos_date = self.pos_date
        df_date = zerocurve.df.loc[pos_date].copy()
        df_date = df_date.set_index("value_dt")
        direction = direction.lower()
        if direction == "parallel":
            df_date["shock"] = shock / 100
        elif direction == "short":
            df_date["shock"] = 0
            df_date.loc[df_date["tenor"] <= 18, "shock"] = shock / 100
        elif direction == "long":
            df_date["shock"] = 0
            df_date.loc[df_date["tenor"] > 18, "shock"] = shock / 100
        else:
            logger.error(f"Unknown value for parameter {direction}.")
            df_date["shock"] = 0
        df_date["shock"] += df_date["rate"]
        df_forward = df_date[["shock", "rate"]].resample("D").mean()
        df_forward["shock"] = df_forward["shock"].interpolate()
        df_forward["rate"] = df_forward["rate"].interpolate()

        df = self.df_cashflows
        df_c = df[df["value_dt"] > self.pos_date]  # Only include future cashflows
        df_returns = df_c.merge(
            df_forward, left_on="value_dt", right_on=df_forward.index
        )
        df_returns["pos_dt"] = pos_date
        df_returns["year_frac"] = round(
            (df_returns["value_dt"] - df_returns["pos_dt"]) / timedelta(365, 0, 0, 0), 5
        )
        df_returns["df_npv"] = (
            1 / (1 + df_returns["rate"] / 100) ** df_returns["year_frac"]
        )
        df_returns["df_shock"] = (
            1 / (1 + df_returns["shock"] / 100) ** df_returns["year_frac"]
        )
        df_returns["npv"] = round(df_returns["cashflow"] * df_returns["df_npv"], 2)
        df_returns["npv_shock"] = round(
            df_returns["cashflow"] * df_returns["df_shock"], 2
        )
        return sum(df_returns["npv_shock"] - df_returns["npv"])

    def calculate_bpv(self, zerocurve: Zerocurve, shock: int = 1) -> pd.DataFrame:
        """Calculate BPV profile, applying the shock to each tenor and calculate the impact"""
        pos_date = self.pos_date
        shock = 1 / 100
        # Current zero curve
        df_zerocurve_date = zerocurve.df.loc[pos_date]

        # Bin cashflows per tenor
        bins = [
            pos_date + pd.offsets.DateOffset(months=item)
            for item in zerocurve.df.loc[pos_date].tenor.to_list()
        ]
        if self.df_cashflows["value_dt"].max() > bins[-1]:
            bins.append(max(self.df_cashflows["value_dt"].max()))
        cats = zerocurve.df.loc[pos_date].tenor.to_list()[
            1:
        ]  # list(range(1, len(bins)))
        df = self.df_cashflows
        df["tenor"] = pd.cut(df["value_dt"], bins, labels=cats, right=False)
        df = df[df["value_dt"] > pos_date]
        df = df[["tenor", "cashflow"]].groupby("tenor").sum("cashflow")

        # Cashflows to numpy
        cashflow = df["cashflow"].to_numpy().reshape(-1, 1)
        # add row for tenor = 0, cashflows at T0 are not included in the cashflow list
        cashflow = np.r_[np.zeros((1, 1)), cashflow]
        # Reshape tenor to year fraction
        t = (df_zerocurve_date["tenor"] / 12).to_numpy().reshape(-1, 1)
        # Zerocurve to numpy
        rates = df_zerocurve_date["rate"].to_numpy()
        # shock rates up and down per tenor point and add as seperate columns
        shock_range = [shock]
        shocks = np.zeros((len(rates), len(rates) * len(shock_range)))
        for s in shock_range:
            for i in range(len(rates)):
                shocks[:, i + shock_range.index(s) * len(rates)] = rates
                shocks[i, i + shock_range.index(s) * len(rates)] = rates[i] + s
        # Reshape rates to concat with shocks
        rates = rates.reshape(len(rates), 1)
        # add shocks to rates
        rates = np.concatenate((rates, shocks), axis=1)
        # calculate discount factor for all rates (including shocked rates)
        discount_factor = (1 / (1 + rates / 100)) ** t
        # calculate the npv for all cashflows under all scenarios
        npv = discount_factor * cashflow
        positive = npv[:, 1 : len(rates) + 1]
        # negative = npv[:, len(rates) + 1 :]
        result = np.sum(
            np.round(positive - npv[:, 0].reshape(-1, 1), 0),
            axis=0,
        ).reshape(
            -1, 1
        )  # np.minimum(positive, negative)
        # Add result to dataframe
        df_result = pd.DataFrame(result)
        df_result["tenor"] = df_zerocurve_date["tenor"].to_list()
        df_result.set_index("tenor", inplace=True)
        df_result.columns = ["dv01"]
        return df_result

    def plot_contracts(self):
        """Simple stacked barplot of outstanding contracts"""
        df = self.df_mortgages
        if len(df):
            return (
                df.sort_values(["start_date", "fixed_period"])
                .pivot_table(
                    index=df["start_date"].dt.year,
                    columns=["fixed_period"],
                    values="principal",
                    aggfunc="count",
                    sort=False,
                )
                .plot(kind="bar", stacked=True)
            )
        else:
            return        

    def plot_cashflows(self):
        """Simple plot of outstanding cashflows from position date"""
        # Cut off all cashflows prior to position date
        df = self.df_cashflows
        df_c = df[df["value_dt"] > self.pos_date]
        df_show = df_c[["cashflow"]].groupby(df_c["value_dt"].dt.strftime("%Y")).sum()
        df_show["cashflow"] = df_show["cashflow"] / 1000
        ax = visualize.barplot(
            df_show,
            x=df_show.index,
            y="cashflow",
            x_label="year",
            y_label="amount (x 1000)",
            title="sum of cashflows per year",
        )
        # using format string '{:.0f}' here but you can choose others
        ax.set_yticks(ax.get_yticks())
        ax.set_yticklabels(["{:0.0f}".format(x) for x in ax.get_yticks().tolist()])
   
    def step(self):
        self.pos_date = self.pos_date + BDay(1)
        self.step_nmd()
