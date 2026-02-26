FOLDER_NAME_VISU = "tdv_visu"

LIBRARY_TZ = "UTC"
DISPLAY_TIMEZONE = "Europe/Paris"

DEFAULT_NAME_VISUALIZATION = "visualization.html"
DEFAULT_QUICK_LOAD = False


class ApiType:
    # To know how type should be interpreted in the API
    FLOAT = "float"
    INT = "int"
    BOOL = "bool"
    TIMESTAMP = "timestamp"
    DAY = "day"
    PATH_FOLDER = "path_folder"
    PATH_FILE = "path_file"


class PatientOptions:
    class PathDataFolder:
        ORDER = 1
        NAME = "data_folder"
        API_TYPE = ApiType.PATH_FOLDER
        DEFAULT = ""
        MANDATORY = True
        DESCRIPTION = "Path to data (folder)"

    class DatetimeStart:
        ORDER = 2
        NAME = "datetime_start"
        API_TYPE = ApiType.TIMESTAMP
        DEFAULT = ""
        MANDATORY = False
        DESCRIPTION = "Time start filter"

    class DatetimeEnd:
        ORDER = 3
        NAME = "datetime_end"
        API_TYPE = ApiType.TIMESTAMP
        DEFAULT = ""
        MANDATORY = False
        DESCRIPTION = "Time end filter"

    class QuickLoad:
        ORDER = 4
        NAME = "quick_load"
        API_TYPE = ApiType.BOOL
        DEFAULT = True
        MANDATORY = False
        DESCRIPTION = "Re-use data if already loaded once"

    # class DataSourceRelative:
    # See local file 'src/clinical_data_visualizer/xxx/options.py'
    # Field 'PatientOptionsDataSourceRelative'
    # For each datasource possible additional informations
    # pass


# From subfield of databse options, depending of datasource
class DatabaseOptions:
    NAME = "database_options"
    API_TYPE = ApiType.PATH_FILE
    DEFAULT = ""
    MANDATORY = True
    DESCRIPTION = "Path to database options (.json)"
    EXTENSION = ".json"

    GLOBAL = "global"  # Only main field for database_options present here, others are directly the class name from datasource file  # noqa: E501

    DEFAULT_PERIOD_RESAMPLING = 1
    DEFAULT_UNIT_FACTOR = 1.0

    FIELD_DISPLAY = "field_display"

    DATA = "data"

    class Data:
        LABEL_CORRESPONDENCE = "label_correspondence"
        UNIT_CONVERSION = "unit_conversion"
        UNIT_RANGE = "unit_range"
        UNIT_INFO = "unit_info"
        DEFAULT_UNIT_INFO = "-"
        COLOR = "color"
        PRIORITY = "priority"
        PERIOD_RESAMPLING = "period_resampling"
        VISIBLE = "visible"
        LINE_DASH = "line_dash"

    NUMERICS = "numerics"

    class Numerics:
        PRIORITY = "priority"
        PERIOD_RESAMPLING = "period_resampling"

    ADDITIONAL_INFORMATIONS = "additional_informations"

    class AdditionalInformations:
        # See local file 'src/clinical_data_visualizer/xxx/options.py'
        # Field 'DatabaseOptionsAdditionalInformations'
        # For each datasource possible additional informations
        pass

    GROUPED_FIELDS = "grouped_fields"

    LOOP = "loop"


class SourceOptions:
    TRACE_OPTIONS = "trace_options"


class PlotType:
    TIME_SERIES = "time_series"
    LOOP = "loop"


if PlotType.LOOP != DatabaseOptions.LOOP:
    msg = "No idea it that would work. Error here to warn you"
    raise NotImplementedError(msg)
