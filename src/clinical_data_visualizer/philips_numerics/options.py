import clinical_data_visualizer.constants as cst

DATASOURCE_NAME = "philips_numerics"
EXPECTED_FOLDER_NAME = "philips_numerics"
FOLDER_KEYWORDS = ["philips", "numerics"]
FILE_KEYWORDS = ["philips_numeric", "numeric", "philips", "num"]
FILE_EXTENSIONS = [".parquet", ".csv"]
MULTI_FILE = False

FILE_NAME_DATAFRAME_LOADED = "philips_numerics_loaded.parquet"

DATA_SOURCE_DEFAULT_TIMEZONE = "UTC"

source_options = {
    cst.SourceOptions.TRACE_OPTIONS: {
        "mode": "lines+markers",
        "line_width": 2.0,
        "line_dash": "solid",
        "opacity": 1.0,
        "marker_symbol": None,
        "marker_size": None,
    },
    "plot_options": {
        "fill_color": None,
        "fill_pattern": None,
    },
}


DEFAULT_DATABASE_OPTIONS = {}


class PatientOptionsDataSourceRelative:
    class TimeShift:
        NAME = "time_shift"
        API_TYPE = cst.ApiType.FLOAT
        DEFAULT = 0.0
        MANDATORY = False
        DESCRIPTION = "Time shift"
