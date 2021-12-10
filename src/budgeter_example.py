from zefdb import *
from zefdb.ops import *
g = Graph()

z_acc = instantiate(ET.Account, g)
z_acc | attach[[
    (RT.Name, "General"),
    (RT.Type, EN.AccountType.Transactional),
]] | collect

z_trans = instantiate(ET.Transaction, g)
z_trans | attach[[
    (RT.Amount, QuantityFloat(10.0, EN.Unit.dollars)),
    (RT.Date, Time("2021 Dec 06 12:00")),
    (RT.Description, "Rising Against Bread Co."),
]] | collect

z_acc | attach[RT.HasEntry, z_trans] | collect

z_acc | now | info | collect

receipt = GraphDelta([
    ET.Transaction["t"],
    (Z["t"], RT.Amount, QuantityFloat(42.0, EN.Unit.dollars)),
    (Z["t"], RT.Date, now()),
    (Z["t"], RT.ID, "123456789"),

    (z_acc, RT.HasEntry, Z["t"])
]) | transact[g]
z_trans2 = receipt["t"]

total = z_acc | now >> L[RT.HasEntry] >> RT.Amount | value | sum | collect
print(f"Total credits in account is {total}")

def get_amount(transaction, account):
    entry = relation(account, RT.HasEntry, transaction)
    return entry >> RT.Amount | value

def get_amount(transaction, account):
    entry = relation(account, RT.HasEntry, transaction)
    if entry | has_out[RT.Amount] | collect:
        return entry >> RT.Amount | value | collect
    else:
        return transaction >> RT.Amount | value | collect

def is_entry_valid(transaction, account):
    entry = relation(account, RT.HasEntry, transaction)
    num_amount_relations = entry | L[RT.Amount] | length | collect + transaction | L[RT.Amount] | length | collect
    return (num_amount_relations == 1)

# Start from a blank slate
g = Graph()

def add_account(g : Graph, name : str, *, desc=None, kind=None):
    actions = [(ET.Account["acc"], RT.Name, name)]
    if desc is not None:
        actions += [(Z["acc"], RT.Description, desc)]
    if kind is not None:
        actions += [(Z["acc"], RT.AccountType, kind)]

    r = GraphDelta(actions) | transact[g]
    return r["acc"]

with Transaction(g):
    z_acc_general = add_account(g, "General")
    z_acc_savings = add_account(g, "Savings", desc="Long term savings", kind=EN.AccountType.Savings)
    z_acc_credit = add_account(g, "Credit card", kind=EN.AccountType.Credit)
g | info | collect

def add_category(g : Graph, name : str, *, goal=None, goal_period=EN.Period.Monthly):
    actions = [(ET.BudgetCategory["cat"], RT.Name, name)]
    if goal is not None:
        actions += [
            (Z["cat"], RT.Goal, goal),
            (Z["cat"], RT.GoalPeriod, goal_period),
        ]
    r = GraphDelta(actions) | transact[g]
    return r["cat"]

with Transaction(g):
    AUD = QuantityFloat(1.0, EN.Unit.AUD)
    add_category(g, "Groceries")
    z_cat_eating_out = add_category(g, "Eating Out", goal=200*AUD)
    z_cat_rates = add_category(g, "Rates", goal=1000*AUD, goal_period=EN.Period.Annually)
z_cat_groceries = g | now | instances[ET.BudgetCategory] | filter[lambda z: value(z >> RT.Name) == "Groceries"] | only | collect
z_cat_groceries

def add_transaction(g : Graph, amount : QuantityFloat, date : Time, *, desc=None, account=None, categories=[]):
    actions = [
        ET.Transaction["t"],
        (Z["t"], RT.Amount, amount),
        (Z["t"], RT.Date, date),
    ]
    if desc is not None:
        actions += [(Z["t"], RT.Description, desc)]

    with Transaction(g):
        r = GraphDelta(actions) | transact[g]
        print(f"Creating transaction with date {r['t'] >> RT.Date | value | collect} and description of {r['t'] >> O[RT.Description] | maybe_value | collect}")
        if account is not None:
            link_account(r["t"], account)
        for category in categories:
            link_category(r["t"], category)
    return r["t"]

add_transaction(g, 13*AUD, now()-1*hours)
add_transaction(g, 42*AUD, now(), desc="Bird food")

@func
def link_account(trans : ZefRef, acc):
    acc = get_account(Graph(trans), acc)
    assert is_a(trans, ET.Transaction)
    assert is_a(acc, ET.Account)

    if not has_relation(acc, RT.HasEntry, trans):
        acc | attach[RT.HasEntry, trans] | collect

@func
def link_category(trans : ZefRef, cat : ZefRef):
    assert is_a(trans, ET.Transaction)
    assert is_a(cat, ET.BudgetCategory)

    if not has_relation(cat, RT.HasEntry, trans):
        cat | attach[RT.HasContribution, trans] | collect

def get_account(g, acc):
    if is_a(acc, str):
        return g | now | instances[ET.Account] | filter[lambda z: value(z >> RT.Name) == acc] | only | collect
    if is_a(acc, ET.Account):
        return acc
    raise Exception(f"Don't know how to obtain account from {acc}")

@func
def link(trans : ZefRef, thing : ZefRef):
    assert is_a(trans, ET.Transaction)

    if is_a(thing, ET.Account):
        link_account(trans, thing)
    elif is_a(thing, ET.BudgetCategory):
        link_category(trans, thing)
    else:
        raise Exception(f"Don't know how to link to object of type {rae_type(thing)}")

# Add all existing transactions to the groceries category and the general account
with Transaction(g):
    for trans in g | now | instances[ET.Transaction]:
        # Using link_account like a regular function
        link_account(trans, z_acc_general)
        # Using link_category like a lazy op, as it was decorated with @func
        trans | link_category[z_cat_groceries] | collect

# Create some more transactions and link them together
with Transaction(g):
    add_transaction(g, 5*AUD, now(), desc="Coffee", account=z_acc_credit, categories=[z_cat_eating_out, z_cat_groceries])
    add_transaction(g, 1000*AUD, Time("2021 Dec 01"), desc="Sad times", account=z_acc_credit, categories=[z_cat_rates])
    add_transaction(g, 20*AUD, Time("2021 Nov 30"), desc="Happy times", account="Credit card", categories=[z_cat_eating_out])
    add_transaction(g, 50*AUD, Time("2021 Dec 03"), account="Credit card", categories=[z_cat_groceries])

import sys
def show_transactions(g : Graph, *, account=None, categories=None, date_from=None, date_to=None, file=sys.stdout):
    # We take the simple approach here, forgoeing any optimisations.

    # If the account or category are passed in as ZefRefs, they will likely be
    # from an older frame of reference. First make sure we are "talking" in the
    # same frame
    frame = now(g)
    nowish = to_frame[frame]

    if account is not None:
        account = get_account(g, account)

    def pred(z : ZefRef):
        if account is not None:
            if not has_relation(nowish(account), RT.HasEntry, z):
                return False
        if categories is not None:
            if not any(has_relation(nowish(category), RT.HasContribution, z) for category in categories):
                return False
        d = value(z >> RT.Date)
        if date_from is not None:
            if d < date_from:
                return False
        if date_to is not None:
            if d > date_to:
                return False

        return True

    # Use tabulate for pretty display
    from tabulate import tabulate

    headers = ["Date", "Amount", "Description", "Account", "Categories"]
    def t_to_list(z : ZefRef):
        date = z >> RT.Date | value | collect
        amount = z >> RT.Amount | value | collect
        desc = z >> O[RT.Description] | value_or[""] | collect
        account = z << O[RT.HasEntry] >> O[RT.Name] | maybe_value | collect
        categories = " & ".join(z << L[RT.HasContribution] >> RT.Name | value | sort[lambda x: x] | collect)

        return [str(date), f"{amount.value} {amount.unit.enum_value}", desc, account, categories]

    data = (frame
            | instances[ET.Transaction]
            | filter[pred]
            | map[t_to_list]
            | sort[lambda l: l[0]]
            | collect)

    print(tabulate(data, headers=headers), file=file)

show_transactions(g)

show_transactions(g, categories=[z_cat_groceries, z_cat_eating_out])

show_transactions(g, date_to=Time("2021-12-02"))

show_transactions(g, account="Credit card", date_from=Time("2021-12-01"))

# Stuff

import zefdb.gql.auto
gd = zefdb.gql.auto.auto_generate_gql(g)
r = gd | transact[g]
print(gd)

import zefdb.gql
z_schema = r["s"]
ariadne_schema = zefdb.gql.generate_gql_api.make_api(z_schema)

s = """query {
  accounts {
    name
    accountType
    hasEntrys {
      date
      amount
    }
  }
  transactions {
    description
    date
    amount
    rev_HasEntrys {
      name
    }
  }
  budgetCategorys {
    name
    goal
    goalPeriod
  }
}"""
q = {"query": s}
from ariadne import graphql_sync
success,result = graphql_sync(ariadne_schema, q)

import json
s = json.dumps(result, indent=2)
print(s)

r = Effect({
    "type": FX.GraphQL.StartServer,
    "port": 5001,
    "api_zefref": z_schema,
    "playground_path": "/",
    "logging": True,
 }) | run
