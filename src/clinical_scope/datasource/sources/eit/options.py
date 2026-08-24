from clinical_scope import constants as cst

DATASOURCE_NAME = "eit"
EXPECTED_FOLDER_NAME = "eit"
FOLDER_KEYWORDS = ["eit"]
FILE_KEYWORDS = []
FILE_EXTENSIONS = [".asc"]
MULTI_FILE = True
FILE_NAME_DATAFRAME_LOADED = "eit.parquet"

DATA_SOURCE_DEFAULT_TIMEZONE = "Europe/Paris"

# EIT filters by time-of-day (filter_date=False), which a min/max datetime range predicate
# can't express — opt out of parquet row-pushdown; it still uses the quick-load cache path
# (ALLOW_QUICK_LOAD unset, defaults True), just without the row filter.
ALLOW_DATETIME_PUSHDOWN = False

Time_column_label = "Time"

# Column naming as it appears in the .asc header: one Global reference channel, one column per
# Local region, and a leading "%" on each ratio derived from them. Matched case-insensitively,
# so these are the canonical spellings rather than the exact bytes on disk.
Global_column_label = "Global"
prefix_local = "Local"
prefix_percentage = "%"

prefix_compliance = "Compliance_"
prefix_smoothed_compliance = "Smoothed_compliance_"
prefix_compliance_loss = "Compliance_loss_%_"

pep = "PEP"
p_crete = "P_crete"


DEFAULT_DATABASE_OPTIONS = {
    "signals": {
        "Global": {"label": "Global", "unit": "Ohms", "color": "black"},
        "Local 1*": {"label": "Local 1", "unit": "Ohms", "color": "red"},
        "Local 2*": {"label": "Local 2", "unit": "Ohms", "color": "blue"},
        "Local 3*": {"label": "Local 3", "unit": "Ohms", "color": "green"},
        "Local 4*": {"label": "Local 4", "unit": "Ohms", "color": "purple"},
        "%Local 1*": {
            "label": "Local 1 %",
            "unit": "Proportion",
            "color": "red",
            "range": [-0.05, 1.05],
        },
        "%Local 2*": {"label": "Local 2 %", "unit": "Proportion", "color": "blue"},
        "%Local 3*": {"label": "Local 3 %", "unit": "Proportion", "color": "green"},
        "%Local 4*": {"label": "Local 4 %", "unit": "Proportion", "color": "purple"},
    },
    "grouped_fields": {
        "Impedance value": ["Global", "Local 1*", "Local 2*", "Local 3*", "Local 4*"],
        "Impedance": ["Global", "%Local 1*", "%Local 2*", "%Local 3*", "%Local 4*"],
    },
}


class DatabaseOptionsAdditionalInformations:
    TIMEZONE = "timezone"


class PatientOptionsDataSourceRelative:
    class TimeShift:
        ORDER = 1
        NAME = "time_shift"
        API_TYPE = cst.ApiType.FLOAT
        DEFAULT = 0.0
        MANDATORY = False
        DESCRIPTION = "Time shift"

    class Day:
        ORDER = 2
        NAME = "day"
        API_TYPE = cst.ApiType.DAY
        DEFAULT = ""
        MANDATORY = False
        DESCRIPTION = "Day of EIT recording"
        PLACEHOLDER = cst.PLACEHOLDER_DAY
