BUILDING_NAMES: dict[str, str] = {
    "ARTS": "Arts Building",
    "B66": "B-66",
    "B67": "B-67",
    "BNSN": "Ezra Taft Benson Building",
    "BRLW": "Barlow Center",
    "BRMB": "George H. Brimhall Building",
    "CANC": "Cannon Center",                      # was: "Cancer Research Center" (wrong)
    "CB": "W.W. Clyde Building",                  # was: "Crabtree Building" (wrong)
    "CONF": "Conference Center",
    "CTB": "Crabtree Technology Building",        # was: "Clyde Building" (wrong)
    "DIST": "Distance Education",
    "EB": "Engineering Building",
    "ELLB": "Leo Ellsworth Building",
    "ESC": "Eyring Science Center",               # was: "Earth Science Building" (wrong)
    "FSSS": "Film Student Support Services",      # was: "Family Sciences Building" (wrong)
    "GLFG": "Golf Course",
    "HAWF": "Harman Building",
    "HBLL": "Harold B. Lee Library",
    "HC": "Hinckley Alumni & Visitors Center",    # was: "Heritage Halls Commons" (wrong)
    "HCEB": "Harman Building",                    # was: "Hinckley Center" (wrong)
    "HGB": "Heber J. Grant Building",             # was: "Harris Fine Arts Center" (wrong)
    "HLRA": "Helaman Halls",
    "HOSP": "Hospital",
    "HRCB": "Herald R. Clark Building",           # was: "Harold R. Clark Building" (wrong first name)
    "HRCN": "HRCN",
    "IPF": "Indoor Practice Facility",
    "JFSB": "Joseph F. Smith Building",
    "JKB": "Jesse Knight Humanities Building",
    "JRCB": "J. Reuben Clark Building",           # was: "John R. Christiansen Building" (wrong)
    "JSB": "Joseph Smith Building",
    "KMBL": "Spencer W. Kimball Tower",
    "LNDC": "London Center",
    "LSB": "Life Sciences Building",
    "LSGH": "Life Sciences Greenhouses",
    "LVES": "LaVell Edwards Stadium",
    "MARB": "Thomas L. Martin Building",          # was: unlabeled (now confirmed)
    "MB": "Music Building",                       # was: "Museum of Art Basement" (wrong)
    "MC": "Marriott Center",                      # was: "Monte L. Bean Museum" (wrong)
    "MCA": "Marriott Center Annex",
    "MCDB": "McDonald Building",
    "MCKB": "David O. McKay Building",
    "MLBM": "Monte L. Bean Life Science Museum",
    "MLRS": "MLRS",
    "MOA": "Museum of Art",
    "MSRB": "Karl G. Maeser Building",
    "NICB": "Joseph K. Nicholes Building",
    "NUF": "NUF",
    "RB": "Stephen L. Richards Building",
    "RBF": "Richards Building Fieldhouse",
    "ROTC": "Daniel H. Wells Building",           # was: "ROTC Building"
    "SAB": "Student Athlete Building",            # was: "Smoot Administration Building" (wrong)
    "SFH": "George Albert Smith Fieldhouse",
    "SFLD": "Soccer Field",
    "SLC": "Salt Lake Center",
    "SNLB": "William H. Snell Building",
    "TCB": "Tennis Courts Building",              # was: "Thomas L. Clyde Building" (wrong)
    "TCF": "TCF",
    "TLRA": "Taylor Building Annex",              # was: "Towers" (wrong)
    "TLRB": "John Taylor Building",               # was: "Towers B" (wrong)
    "TMCB": "James E. Talmage Building",
    "TNRB": "N. Eldon Tanner Building",
    "TRAK": "Track & Field",
    "TRPN": "TRPN",
    "TRPS": "TRPS",
    "UPC": "University Parkway Center",           # was: "University Press / Creative Works" (wrong)
    "WCAS": "WCAS",
    "WCCB": "WCCB",
    "WCCL": "WCCL",
    "WCOB": "Marriott School of Business",
    "WSC": "Wilkinson Student Center",
    "WVB": "West View Building",                  # was: "Wymount Village" (wrong)
}

ALL_BUILDINGS: list[str] = [
    "ARTS", "B66", "B67", "BNSN", "BRLW", "BRMB", "CANC", "CB", "CONF", "CTB",
    "DIST", "EB", "ELLB", "ESC", "FSSS", "GLFG", "HAWF", "HBLL", "HC", "HCEB",
    "HGB", "HLRA", "HOSP", "HRCB", "HRCN", "IPF", "JFSB", "JKB", "JRCB", "JSB",
    "KMBL", "LNDC", "LSB", "LSGH", "LVES", "MARB", "MB", "MC", "MCA", "MCDB",
    "MCKB", "MLBM", "MLRS", "MOA", "MSRB", "NICB", "NUF", "RB", "RBF", "ROTC",
    "SAB", "SFH", "SFLD", "SLC", "SNLB", "TCB", "TCF", "TLRA", "TLRB", "TMCB",
    "TNRB", "TRAK", "TRPN", "TRPS", "UPC", "WCAS", "WCCB", "WCCL", "WCOB", "WSC", "WVB",
]


def get_display_name(code: str) -> str:
    return BUILDING_NAMES.get(code, code)
