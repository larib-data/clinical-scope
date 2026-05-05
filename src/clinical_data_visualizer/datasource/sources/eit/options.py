from clinical_data_visualizer import constants as cst

DATASOURCE_NAME = "eit"
EXPECTED_FOLDER_NAME = "eit"
FOLDER_KEYWORDS = ["eit"]
FILE_KEYWORDS = []
FILE_EXTENSIONS = [".asc"]
MULTI_FILE = True
FILE_NAME_DATAFRAME_LOADED = "eit.parquet"

DATA_SOURCE_DEFAULT_TIMEZONE = "Europe/Paris"

# Many names here should be moved in example_eit_options.json file
Time_column_label = "Time"

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
