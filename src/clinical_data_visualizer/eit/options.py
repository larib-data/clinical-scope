from clinical_data_visualizer import constants as cst

EXPECTED_FOLDER_NAME = "eit"
FOLDER_KEYWORDS = ["eit"]
KEYWORD_FILE_EXTENSION = ".asc"
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
    "data": {
        "label_correspondence": {
            "Global": "Global",
            "Local 1*": "Local 1",
            "Local 2*": "Local 2",
            "Local 3*": "Local 3",
            "Local 4*": "Local 4",
            "%Local 1*": "Local 1 %",
            "%Local 2*": "Local 2 %",
            "%Local 3*": "Local 3 %",
            "%Local 4*": "Local 4 %",
        },
        "unit_conversion": {
            "Global": 1.0,
            "Local 1*": 1.0,
            "Local 2*": 1.0,
            "Local 3*": 1.0,
            "Local 4*": 1.0,
        },
        "unit_info": {
            "Global": "Ohms",
            "Local 1*": "Ohms",
            "Local 2*": "Ohms",
            "Local 3*": "Ohms",
            "Local 4*": "Ohms",
            "%Local 1*": "Proportion",
            "%Local 2*": "Proportion",
            "%Local 3*": "Proportion",
            "%Local 4*": "Proportion",
        },
        "color": {
            "Global": "black",
            "Local 1*": "red",
            "Local 2*": "blue",
            "Local 3*": "green",
            "Local 4*": "purple",
            "%Local 1*": "red",
            "%Local 2*": "blue",
            "%Local 3*": "green",
            "%Local 4*": "purple",
        },
        "unit_range": {"%Local 1*": [-0.05, 1.05]},
    },
    "field_display": [
        "Global",
        "Local 1*",
        "Local 2*",
        "Local 3*",
        "Local 4*",
        "%Local 1*",
        "%Local 2*",
        "%Local 3*",
        "%Local 4*",
    ],
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
