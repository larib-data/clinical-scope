import clinical_data_visualizer.constants as cst

EXPECTED_FOLDER_NAME = "philips_numerics"
FOLDER_KEYWORDS = ["philips", "numerics"]
KEYWORD_FILE = "numerics"

FILE_NAME_DATAFRAME_LOADED = "philips_numerics_loaded.parquet"

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


class PatientOptionsDataSourceRelative:
    class TimeShift:
        NAME = "time_shift"
        API_TYPE = cst.ApiType.FLOAT
        DEFAULT = 0.0
        MANDATORY = False
        DESCRIPTION = "Time shift"
