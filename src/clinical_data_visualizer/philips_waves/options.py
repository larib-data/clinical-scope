import clinical_data_visualizer.constants as cst

DATASOURCE_NAME = "philips_waves"
EXPECTED_FOLDER_NAME = "philips_waves"
FOLDER_KEYWORDS = ["philips", "waves"]
FILE_KEYWORDS = ["philips_wave", "waveform", "wave", "timeseries", "data", "signal", "philips"]
FILE_EXTENSIONS = [".parquet", ".csv"]
MULTI_FILE = False

FILE_NAME_DATAFRAME_LOADED = "philips_waves.parquet"

ALLOW_QUICK_LOAD = False

DATA_SOURCE_DEFAULT_TIMEZONE = "Europe/Paris"


DEFAULT_DATABASE_OPTIONS = {}


class PatientOptionsDataSourceRelative:
    class TimeShift:
        NAME = "time_shift"
        API_TYPE = cst.ApiType.FLOAT
        DEFAULT = 0.0
        MANDATORY = False
        DESCRIPTION = "Time shift"
