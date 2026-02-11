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
    "field_display": ["Local 1*", "Local 2*", "Local 3*", "Local 4*"],
}


class DatabaseOptionsAdditionalInformations:
    PERCENTAGE_REF_COLUMN = "percentage_reference_column"
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
