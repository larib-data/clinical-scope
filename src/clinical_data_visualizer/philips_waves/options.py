import clinical_data_visualizer.constants as cst

KEYWORD_FILE = "waves"

FILE_NAME_DATAFRAME_LOADED = "philips_waves.parquet"

ALLOW_LOADED_DATAFRAME_SAVING = False


class PatientOptionsDataSourceRelative:
    class TimeShift:
        NAME = "time_shift"
        API_TYPE = cst.ApiType.FLOAT
        DEFAULT = 0.0
        MANDATORY = False
        DESCRIPTION = "Time shift"
