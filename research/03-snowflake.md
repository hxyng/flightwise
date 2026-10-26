# Snowflake research for flight-delay hackathon (2026-10-26)

**TL;DR**
1. No free Marketplace listing for US flight on-time/delay data was found (only OAG paid; Snowflake's own USDOT source is T-100 traffic, no delays). Fastest path: download BTS monthly CSV zips and upload via Snowsight (250 MB/file, 250 files) or PUT + COPY INTO.
2. CoCo = Snowflake's AI coding agent (formerly Cortex Code); in Snowsight Workspaces, plus CLI `cortex`. 30-day individual trial at signup.snowflake.com/cortex-code.
3. Auth: trial accounts are EXEMPT from the password/MFA phases (per docs), so password login should still work; for non-trial accounts use a PAT passed as `password=` or key-pair (`SNOWFLAKE_JWT`).

## Premises check
- "Trial = free 30 days, $400 credit": NOT verified in this research (not fetched). Unknown; check signup page.
- "May not have dataset": consistent; I found no ready Marketplace flight-delay dataset.

## 1. Getting flight data in

### Marketplace (negative result, partly unverified)
- Searches found NO free Marketplace listing of BTS On-Time Performance. I could not browse the Marketplace itself (needs login), so "none exists" is unconfirmed. Spend 2 minutes in Snowsight: Data Products > Marketplace, search "flight", "airline", "BTS", filter Price = Free.
- Related, but not delay data:
  - Snowflake Public Data (Free), listing https://app.snowflake.com/marketplace/listing/GZTSZ290BV255/snowflake-public-data-products-snowflake-public-data-free (90+ public sources; free tier ~3-month lag). Docs page for its USDOT source: https://data-docs.snowflake.com/foundations/sources/usdot - this is T-100 Domestic Segment (traffic/market share), NOT delays. Table/column names: unknown (not fetched).
  - OAG "Flight Info Direct" on Snowflake: commercial, worldwide, flight status; pricing unknown, not confirmed free.
- Database/schema/table/column names for any free flight-delay listing: unknown.

### Fallback: BTS On-Time files
- Source: BTS TranStats "Reporting Carrier On-Time Performance (1987-present)". Monthly prezipped files, from memory (UNVERIFIED) like
  `https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_<YEAR>_<MONTH>.zip`. Roughly 600K+ rows/month (Apify page); zip size unknown. Note BTS issued a "Technical Directive No 40 On-Time 2026" (https://www.bts.gov/sites/bts.dot.gov/files/2025-11/Technical%20Directive%20No%2040%20On-Time%202026.pdf) - not read; schema may have changed for 2026 files, check column list.
- Hackathon-sized plan: pick 1-3 recent months (or one full year 2024), unzip CSVs.
- Snowsight upload (https://docs.snowflake.com/en/user-guide/data-load-web-ui): Create > Table > From File; up to 250 files, 250 MB each; CSV/TSV/JSON/Parquet etc.; infers schema. Needs role with CREATE TABLE and USAGE on a stage. Larger: use Snowflake CLI (`snow stage copy`) or SnowSQL `PUT`.
- Stage + COPY INTO pattern (standard Snowflake, not re-verified this session):
```sql
CREATE DATABASE FLIGHTS; CREATE SCHEMA FLIGHTS.BTS;
CREATE STAGE FLIGHTS.BTS.RAW;
CREATE FILE FORMAT FLIGHTS.BTS.CSVFF TYPE=CSV SKIP_HEADER=1 FIELD_OPTIONALLY_ENCLOSED_BY='"' NULL_IF=('') ;
-- PUT file://C:\data\*.csv @FLIGHTS.BTS.RAW;   (SnowSQL / snow stage copy)
-- Easiest: create table via Snowsight upload, or INFER_SCHEMA + CREATE TABLE ... USING TEMPLATE, then COPY INTO.
```
- Typical column names in the BTS file (from memory, verify against actual header): Year, Month, DayofMonth, FlightDate, Reporting_Airline, Origin, Dest, CRSDepTime, DepTime, DepDelay, DepDel15, CRSArrTime, ArrTime, ArrDelay, ArrDel15, Cancelled, CancellationCode, Diverted, Distance, CarrierDelay, WeatherDelay, NASDelay, SecurityDelay, LateAircraftDelay.
- Tip: BTS CSVs have trailing comma/empty last column; Snowsight inference may add a blank column. Use ERROR_ON_COLUMN_COUNT_MISMATCH=FALSE.

## 2. CoCo (Cortex Code)
- Official docs: https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code . "Snowflake CoCo" is an AI agent built into the platform (data eng, analytics, ML, agents), aware of RBAC and schemas. Third-party source (Kanerika, unverified) says it was renamed from Cortex Code at Summit 2026.
- Surfaces: Snowsight (Workspaces and admin pages), desktop app, CLI. In Workspaces it uses the open SQL file/notebook as context. Third-party guide: click the CoCo icon (blue star) bottom-right of a Workspace/worksheet. Account admin must enable it on the CoCo Admin page; needs cross-region inference enabled; Commercial regions.
- Cost: individuals can sign up at signup.snowflake.com/cortex-code for a 30-day trial with fixed usage; then paid unless cancelled. Existing accounts: pay-as-you-go token billing. (Whether CoCo works in a plain $400-credit trial: unknown.)
- CLI install (https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code-cli):
  - Windows PowerShell: `irm https://ai.snowflake.com/static/cc-scripts/install.ps1 | iex`
  - mac/Linux/WSL: `curl -LsS https://ai.snowflake.com/static/cc-scripts/install.sh | sh`
  - Run `cortex`; wizard reads/creates `~/.snowflake/connections.toml` (same file as `snow` CLI). `cortex --model auto`; `/model`, `/guardrails`.
- Explore a table: just prompt in natural language, e.g. "What databases do I have access to?", "Describe FLIGHTS.BTS.ONTIME and show the 10 airports with worst avg ArrDelay". Docs give no step-by-step; this is general usage.

## 3. snowflake-connector-python

### Account identifier
- Use `orgname-accountname` (or legacy `locator.region`), WITHOUT `.snowflakecomputing.com` (docs: https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-connect). Find in Snowsight: user menu > account details.

### Auth changes 2025-2026 (https://docs.snowflake.com/en/user-guide/security-mfa-rollout; dates are estimates, rolling per account)
- Phase 1 Sep 2025-Jan 2026: MFA mandatory for password sign-in to Snowsight.
- Phase 2 May-Jul 2026: new human users need 2nd factor for password sign-in even via BI tools; `LEGACY_SERVICE` can't be assigned.
- Phase 3 Aug-Oct 2026 (i.e. NOW): MFA for all human users; non-human users blocked from passwords; LEGACY_SERVICE migrated to SERVICE.
- Docs say: "Trial and reader accounts ... the phases don't apply, so single-factor passwords remain allowed." So a fresh trial account's username+password via connector should work. Caveat: this is the doc page's current wording; verify by testing.
- If your account is non-trial: use PAT, key-pair, OAuth, or MFA/SSO (externalbrowser).

### PAT (https://docs.snowflake.com/en/user-guide/programmatic-access-tokens)
```sql
ALTER USER IF EXISTS <me> ADD PROGRAMMATIC ACCESS TOKEN hack_token ROLE_RESTRICTION='ACCOUNTADMIN' DAYS_TO_EXPIRY=7;
-- secret shown once. Service users need a network policy; person users need one to AUTHENTICATE with a PAT (unless PAT_POLICY changes it).
```
Use: pass the token as `password=` (docs example; Airflow docs agree no special authenticator). `authenticator="PROGRAMMATIC_ACCESS_TOKEN"` is unconfirmed - don't rely on it. The network-policy requirement is the likely hackathon gotcha (ALLOWED_IP_LIST with your IP).

### Key-pair
`authenticator="SNOWFLAKE_JWT"`, `private_key_file=<path>`, `private_key_file_pwd`/`private_key_password` (docs say `private_key_file_pwd` is deprecated; use `private_key_password`).

### Minimal code (.env: SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD [or PAT], SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA, SNOWFLAKE_ROLE)
```python
import os, snowflake.connector
from dotenv import load_dotenv
load_dotenv()
def conn():
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],      # orgname-accountname
        user=os.environ["SNOWFLAKE_USER"],            # LOGIN_NAME
        password=os.environ["SNOWFLAKE_PASSWORD"],   # password or PAT
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],  # e.g. COMPUTE_WH
        database=os.environ["SNOWFLAKE_DATABASE"],
        schema=os.environ["SNOWFLAKE_SCHEMA"],
        role=os.environ.get("SNOWFLAKE_ROLE"),
    )
with conn() as c:
    cur = c.cursor()
    cur.execute("SELECT ORIGIN, AVG(ARRDELAY) d FROM ONTIME GROUP BY 1 ORDER BY d DESC LIMIT 10")
    df = cur.fetch_pandas_all()   # needs: pip install "snowflake-connector-python[pandas]"
    # schema string for an LLM prompt:
    cur.execute("""SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
                   FROM INFORMATION_SCHEMA.COLUMNS
                   WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME, ORDINAL_POSITION""",
                (os.environ["SNOWFLAKE_SCHEMA"].upper(),))
    rows = cur.fetchall()
    schema_str = "\n".join(f"{t}.{c} {d}" for t, c, d in rows)
```
Notes: column names come back UPPERCASE in pandas; `fetch_pandas_all` page example not verified in docs this session (the connect page had none). INFORMATION_SCHEMA is scoped to the current database. Remember a running warehouse is needed (create XSMALL, AUTO_SUSPEND=60).

## Not checked
Marketplace UI itself (login-gated); trial credit amount; exact BTS URL/sizes/2026 column changes; whether CoCo is enabled in plain trial accounts; exact connector PAT docs section.

## Sources
- https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code
- https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code-cli
- https://docs.snowflake.com/en/user-guide/security-mfa-rollout
- https://docs.snowflake.com/en/user-guide/programmatic-access-tokens
- https://docs.snowflake.com/en/user-guide/data-load-web-ui
- https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-connect
- https://data-docs.snowflake.com/foundations/sources/usdot
- https://www.oag.com/flight-info-direct-aviation-data
