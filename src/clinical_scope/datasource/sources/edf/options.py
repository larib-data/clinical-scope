import datetime

import clinical_scope.constants as cst

DATASOURCE_NAME = "edf"
EXPECTED_FOLDER_NAME = "edf"
FOLDER_KEYWORDS = ["edf"]
FILE_KEYWORDS = []
FILE_EXTENSIONS = [".edf"]
MULTI_FILE = True

FILE_NAME_DATAFRAME_LOADED = "edf.parquet"

# EDF stores a wall-clock start with no offset, so the recording is read in device-local time.
DATA_SOURCE_DEFAULT_TIMEZONE = "Europe/Paris"

# A recording with no start date is re-dated from the `day` option in _format, so the index a
# cached read filters on is not the index the datetime window applies to — a min/max row
# predicate can't express that. Opt out of parquet row-pushdown; _filter_by_datetime still cuts.
ALLOW_DATETIME_PUSHDOWN = False

# The header always carries a start date and a start time, but a de-identified file zeroes
# them: EDF+ mandates 01.01.85 for an unknown date, and some writers use the Unix epoch. Either
# means "no date in the file", which lets `recording_start` supply one — see
# EDFDataSource._anchor_undated_recording.
UNKNOWN_START_DATES = (
    datetime.date(1985, 1, 1),
    datetime.date(1970, 1, 1),
)
# The single date every undated recording is normalized to at load time.
CANONICAL_UNKNOWN_START_DATE = UNKNOWN_START_DATES[0]


DEFAULT_DATABASE_OPTIONS = {}


class DatabaseOptionsAdditionalInformations:
    TIMEZONE = cst.DatabaseOptions.AdditionalInformations.TIMEZONE


class PatientOptionsDataSourceRelative:
    class TimeShift:
        ORDER = 1
        NAME = "time_shift"
        API_TYPE = cst.ApiType.FLOAT
        DEFAULT = 0.0
        MANDATORY = False
        DESCRIPTION = "Time shift"

    class RecordingStart:
        ORDER = 2
        NAME = "recording_start"
        API_TYPE = cst.ApiType.TIMESTAMP
        DEFAULT = ""
        MANDATORY = False
        DESCRIPTION = "Recording start, in device time (date alone to keep the file's time of day)"
        PLACEHOLDER = cst.PLACEHOLDER_TIMESTAMP
