"""
# Name: Rapid Benefit Indicator Assessment - All Modules (Tier 1)
# Purpose: Calculate values for benefit indicators using wetland
#          restoration site polygons and a variety of other input data
# Author: Justin Bousquin
# Additional Author Credits: Michael Charpentier (Report generation)
# Additional Author Credits: Marc Weber and Tad Larsen (StreamCat)

# Version Notes:
# Developed in ArcGIS 10.3
# 0.1.0 Tool complete and ran for case study using this version
"""

import os
import time
import arcpy
import subprocess
from itertools import chain
from urllib import urlretrieve
from shutil import rmtree
from decimal import Decimal
from collections import deque, defaultdict


def create_outTbl(sites, outTbl):
    """create copy of sites to use for processing and results
    Notes: this also creates an "orig_ID" field to retain @OID
    """
    #check if outTbl already exists, and delete if so
    del_exists(outTbl)
    arcpy.CopyFeatures_management(sites, outTbl)
    # Check if "orig_ID" field exists already
    if field_exists(outTbl, "orig_ID"):
        message("orig_ID field already exists in sites, it will be used " +
                "to maintain unique site IDs")
    else:
        #create field for orig OID@
        arcpy.AddField_management(outTbl, "orig_ID", "DOUBLE")
        with arcpy.da.UpdateCursor(outTbl, ["OID@", "orig_ID"]) as cursor:
            for row in cursor:
                row[1] = row[0]
                cursor.updateRow(row)


def get_ext(FC):
    """get extension"""
    ext = arcpy.Describe(FC).extension
    if len(ext)>0:
        ext = "." + ext
    return ext


def dec(x):
    """decimal.Decimal"""
    return Decimal(x)


def mean(l):
    "get mean of list"
    return sum(l)/float(len(l))


def deleteFC_Lst(lst):
    """delete listed feature classes or layers
    Purpose: delete feature classes or layers using a list."""
    for l in lst:
        arcpy.Delete_management(l)
        

def SocEqu_BuffDist(lst):
    """Buffer Distance for Social equity based on lst benefits
    Purpose: Returns a distance to use for the buffer based on which
             benefits are checked and how far those are delivered.
    """
    #ck[0, 4] = [flood, view, edu, rec, bird]
    if lst[0] is not None:
        buff_dist = "2.5 Miles"
    elif lst[3] is not None:
        buff_dist = "0.33 Miles"
    elif lst[2] is not None:
        buff_dist = "0.25 Miles"
    elif lst[4] is not None:
        buff_dist = "0.2 Miles"
    elif lst[1] is not None:
        buff_dist = "100 Meters"
    else:
        message("No benefits selected, default distance for Social Equity " +
                "will be 2.5 Miles")
        buff_dist = "2.5 Miles"
    return buff_dist


def exportReport(pdfDoc, pdf_path, pg_cnt, mxd):
    """pdf from mxd"""
    pdf = pdf_path + "report_page_" + str(pg_cnt) + ".pdf"
    del_exists(pdf)
    arcpy.mapping.ExportToPDF(mxd, pdf, "PAGE_LAYOUT")
    pdfDoc.appendPages(pdf)
    arcpy.Delete_management(pdf, "")


def textpos(theText,column,indnumber):
    """position text on report
    Author Credit: Mike Charpentier
    """
    if column == 1:
        theText.elementPositionX = 6.25
    else:
        theText.elementPositionX = 7.15
    ypos = 9.025 - ((indnumber - 1) * 0.2)
    theText.elementPositionY = ypos
    

def boxpos(theBox,column,indnumber):
    """position box on report
    Author Credit: Mike Charpentier 
    """
    if column == 1:
        theBox.elementPositionX = 5.8
    else:
        theBox.elementPositionX = 6.7
    ypos = 9 - ((indnumber - 1) * 0.2)
    theBox.elementPositionY = ypos


def fldExists(fieldName,colNumber,rowNumber, fieldInfo, blackbox):
    """report
    Author Credit: Mike Charpentier 
    """
    fldIndex = fieldInfo.findFieldByName(fieldName)
    if fldIndex > 0:
        return True
    else:
        newBox = blackbox.clone("_clone")
        boxpos(newBox,colNumber,rowNumber)
        return False


def proctext(fieldVal, fieldType, ndigits, ltorgt, aveVal, colNum, rowNum,
             allNos, mxd):
    """Author Credit: Mike Charpentier
    """
    # Map elements
    graphic = "GRAPHIC_ELEMENT"
    txt = "TEXT_ELEMENT"
    bluebox = arcpy.mapping.ListLayoutElements(mxd, graphic, "bluebox")[0]
    redbox = arcpy.mapping.ListLayoutElements(mxd, graphic, "redbox")[0]
    graybox = arcpy.mapping.ListLayoutElements(mxd, graphic, "graybox")[0]
    blackbox = arcpy.mapping.ListLayoutElements(mxd, graphic, "blackbox")[0]
    indtext = arcpy.mapping.ListLayoutElements(mxd, txt, "IndText")[0]

    # Process the box first so that text draws on top of box
    if fieldVal is None or fieldVal == ' ':
        newBox = blackbox.clone("_clone")
    else:
        if fieldType == "Num":  # Process numeric fields
            if ltorgt == "lt":
                if fieldVal < aveVal:
                    newBox = bluebox.clone("_clone")
                else:
                    newBox = redbox.clone("_clone")
            else:
                if fieldVal > aveVal:
                    newBox = bluebox.clone("_clone")
                else:
                    newBox = redbox.clone("_clone")
        else: # Process text fields (booleans)
            if allNos == 1:
                newBox = graybox.clone("_clone")
            else:
                if fieldVal == aveVal:
                    newBox = bluebox.clone("_clone")
                else:
                    newBox = redbox.clone("_clone")
    boxpos(newBox,colNum,rowNum)
    # Process the text
    if not (fieldVal is None or fieldVal == ' '):
        newText = indtext.clone("_clone")
        if fieldType == "Num":  # Process numeric fields
            if fieldVal == 0:
                newText.text = "0"
            else:
                if ndigits == 0:
                    if fieldVal > 10:
                        rndnumber = round(fieldVal,0)
                        intnumber = int(rndnumber)
                        newnum = format(intnumber, ",d")
                        newText.text = newnum
                    else:
                        newText.text = str(round(fieldVal,1))
                else:
                    newText.text = str(round(fieldVal,ndigits))
        else: #boolean fields
            if allNos == 1:
                newText.text = "No"
            else:
                if fieldVal == "YES":
                    newText.text = "Yes"
                else:
                    newText.text = "No"
        textpos(newText,colNum,rowNum)


def tbl_fieldType(table, field):
    """Return data type for a field in a table"""
    fields = arcpy.ListFields(table)
    for f in fields:
        if f.name == field:
            return f.type
            break


def ListType_fromField(typ, lst):
    """list type from field
    Purpose: map python list type based on field.type
    Example: lst = type_fromField(paramas[1].type, params[2].values)
             where (field Obj; list of unicode values).
    """
    if typ in ["Single", "Float", "Double"]:
        return map(float, lst)
    elif typ in ["SmallInteger", "Integer"]: #"Short" or "Long"
        return map(int, lst)
    else: #String #Date?
        try:
            return map(str, lst)
        except:
            message("Could not recongnize field type")


def nhdPlus_check(catchment, joinField, relTbl):
    """check NHD+ inputs
    Purpose: Assigns defaults and/or checks the NHD Plus inputs.
    """
    script_dir = os.path.dirname(os.path.realpath(__file__)) + os.sep
    NHD_gdb = "NHDPlusV21" + os.sep + "NHDPlus_Downloads.gdb"
    if catchment == None:
        catchment = script_dir + NHD_gdb + os.sep + "Catchment"
    if arcpy.Exists(catchment):
        message("Catchment file for downstream:\n{}".format(catchment))
        if joinField == None:
            joinField = "FEATUREID" #field from feature layer
        #check catchment for field
        if not field_exists(catchment, joinField):
            message("'{}' field could not be found in:\n".format(joinField,
                                                                 catchment))
            return False
    else:
        message("Catchment file not in expected location:\n" + catchment)
        return False
    if relTbl == None:
        relTbl = script_dir + NHD_gdb + os.sep + "PlusFlow"
    if arcpy.Exists(relTbl):
        message("Downstream relationships table:\n{}".format(relTbl))
        #check relationship table for field "FROMCOMID" & "TOCOMID"
        for targetField in ["FROMCOMID", "TOCOMID"]:
            if not field_exists(relTbl , targetField):
                message("'{}' field could not be found in:\n{}".format(
                    targetField, relTbl))
                return False
    else:
        message("Default relationship file not in expected location:\n" +
                relTbl)
        return False
    message("NHD Plus Inputs are OK")
    return catchment, joinField, relTbl


def list_downstream(lyr, field, COMs):
    """List catchments downstream of catchments in layer
    Notes: can be re-written to work for upstream
    """
    #list lyr IDs
    HUC_ID_lst = field_to_lst(lyr, field)
    #list catchments downstream of site
    downCatchments = []
    for ID in set(HUC_ID_lst):
        downCatchments.append(children(ID, COMs))
        #upCatchments.append(children(ID, UpCOMs))
        #list catchments upstream of site #alt
    #flatten list and remove any duplicates
    downCatchments = set(list(chain.from_iterable(downCatchments)))
    return(list(downCatchments))


def children(token, tree):
    """List children
    Purpose: returns list of all children"""
    visited = set()
    to_crawl = deque([token])
    while to_crawl:
        current = to_crawl.popleft()
        if current in visited:
            continue
        visited.add(current)
        node_children = set(tree[current])
        to_crawl.extendleft(node_children - visited)
    return list(visited)
            

def setNHD_dict(Flow):
    """Read in NHD Relates
    Purpose: read the upstream/downstream table to memory"""
    UpCOMs = defaultdict(list)
    DownCOMs = defaultdict(list)
    message("Gathering info on upstream / downstream relationships")
    with arcpy.da.SearchCursor(Flow, ["FROMCOMID", "TOCOMID"]) as cursor:
        for row in cursor:
            FROMCOMID = row[0]
            TOCOMID = row[1]
            if TOCOMID != 0:
                UpCOMs[TOCOMID].append(TOCOMID)
                DownCOMs[FROMCOMID].append(TOCOMID)
    return (UpCOMs, DownCOMs)


def HTTP_download(request, directory, filename):
    """Download HTTP request to filename
    Param request: HTTP request link ending in "/"
    Param directory: Directory where downloaded file will be saved
    Param filename: Name of file for download request and saving
    """
    host = "http://www.horizon-systems.com/NHDPlus/NHDPlusV2_data.php"
    #add dir to var zipfile is saved as
    f = directory + os.sep + filename
    r = request + filename
    try:
        urlretrieve(r, f)
        message("HTTP downloaded successfully as:\n" + str(f))
    except:
        message("Error downloading from: " + '\n' + str(r))
        message("Try manually downloading from: " + host)


def WinZip_unzip(directory, zipfile):
    """Use program WinZip in C:\Program Files\WinZip to unzip .7z"""
    message("Unzipping download...")
    message("Winzip may open. If file already exists you will be prompted...")
    d = directory
    z = directory + os.sep + zipfile
    try:
        zipExe = r"C:\Program Files\WinZip\WINZIP64.EXE"
        args = zipExe + ' -e ' + z + ' ' + d
        subprocess.call(args, stdout=subprocess.PIPE)
        message("Successfully extracted NHDPlus data to:\n" + d)
        os.remove(z)
        message("Deleted zipped NHDPlus file")
    except:
        message("Unable to extract NHDPlus files. " +
                "Try manually extracting the files from:\n" + z)
        message("Software to extract '.7z' files can be found at: " +
                "http://www.7-zip.org/download.html")


def append_to_default(out_file, in_file, msg):
    """Pull downloaded catchments/flow tables into defaults in gdb
    """
    folder = os.path.dirname(in_file)
    gdb = os.path.dirname(out_file)
    f = os.path.basename(out_file)
    # Check that sub-folder exists in download
    if os.path.isdir(folder):
        # Find the file in that folder
        if arcpy.Exists(in_file):
            # Find the default Feature Class or table
            if arcpy.Exists(out_file):
                # Append the downloaded into the default
                arcpy.Append_management(in_file, out_file, "NO_TEST")
                message("Downloaded {} added to:\n{}".format(msg, out_file))
                # Delete downloaded
                try:
                    rmtree(folder)
                    message("Original downloaded {} folder deleted".format(msg))
                except:
                    message("Unable to delete downloaded {} folder".format(msg))
            else:
                message("Expected '{}' not found in '{}'".format(f, gdb))
        else:
            message("Expected download file '{}' not found".format(in_file))
    else:
        message("Expected download folder '{}' not found".format(folder))


def view_score(lst_50, lst_100):
    """Calculate Weighted View Score
    Purpose: list of weighted view scores.
    Notes: Does not currently test that the lists are of equal length.
    """
    lst =[]
    #add test for equal length of lists? (robust check, but shouldn't happen)
    #if len(lst_50) != len(lst_100):
    #   arcpy.AddMessage("Error in view score function, unequal list lengths")
    #   break
    for i, item in enumerate(lst_50):
       lst.append(item * 0.7 + lst_100[i] * 0.3)
    return lst


def setParam(str1, str2, str3, str4="", str5="", multiValue=False):
    """Set Input Parameter
    Purpose: Returns arcpy.Parameter for provided string,
             setting defaults for missing.
    """
    lst = [str1, str2, str3, str4, str5]
    defLst = ["Input", "name", "GpFeatureLayer", "Required", "Input"]
    for i, str_ in enumerate(lst):
        if str_ =="":
            lst[i]=defLst[i]
    return arcpy.Parameter(
        displayName = lst[0],
        name = lst[1],
        datatype = lst[2],
        parameterType = lst[3],
        direction = lst[4],
        multiValue = multiValue)


def disableParamLst(lst):
    """Disable Parameter List
    Purpose: disables input fields for a list of parameters.
    """
    for field in lst:
        field.enabled = False
    

def message(string):
    """Generic message
    Purpose: prints string message in py or pyt.
    """
    arcpy.AddMessage(string)
    print(string)


def exec_time(start, task):
    """Global Timer
    Purpose: Returns the time since the last function assignment,
             and a task message.
    Notes: used during testing to compare efficiency of each step
    """
    end = time.clock()
    comp_time = time.strftime("%H:%M:%S", time.gmtime(end-start))
    message("Run time for " + task + ": " + str(comp_time))
    start = time.clock()
    return start


def field_exists(table, field):
    """Check if field exists in table
    Notes: return true/false
    """
    fieldList = [f.name for f in arcpy.ListFields(table)]
    return True if field in fieldList else False


def del_exists(item):
    """ Delete if exists
    Purpose: if a file exists it is deleted and noted in a message.
    """
    if arcpy.Exists(item):
        arcpy.Delete_management(item)
        message(str(item) + " already exists, " +
                "it was deleted and will be replaced.")


def check_vars(outTbl, addresses, popRast):
    """Check variables
    Purpose: make sure population var has correct spatial reference.
    """
    if addresses is not None:
        addresses = checkSpatialReference(outTbl, addresses) #check spatial ref
        message("Addresses OK")
        return addresses, None
    elif popRast is not None: #NOT YET TESTED
        popRast = checkSpatialReference(outTbl, popRast) #check projection
        message("Population Raster OK")
        return None, popRast
    else:
        arcpy.AddError("No population inputs specified")
        print("No population inputs specified")
        raise arcpy.ExecuteError


def checkSpatialReference(match_dataset, in_dataset, output = None):
    """Check Spatial Reference
    Purpose: Checks that in_dataset spatial reference name matches
             match_dataset and re-projects if not.
    Inputs: \n match_dataset(Feature Class/Feature Layer/Feature Dataset):
            The dataset with the spatial reference that will be matched.
            in_dataset (Feature Class/Feature Layer/Feature Dataset):
            The dataset that will be projected if it does not match.
    output: \n Path, filename and extension for projected in_dataset
            Defaults to match_dataset location.
    Return: \n Either the original FC or the projected 'output' is returned.
    """
    matchSR = arcpy.Describe(match_dataset).spatialReference
    otherSR = arcpy.Describe(in_dataset).spatialReference
    if matchSR.name != otherSR.name:
        message("Spatial reference for '{}' does not match.".format(in_dataset))
        try:
            if output is None:
                # Output defaults to match_dataset location
                path = os.path.dirname(match_dataset)
                p_ext = "_prj" + get_ext(match_dataset)
                out_name = os.path.splitext(os.path.basename(in_dataset))[0]
                output = path + os.sep + out_name + p_ext
            del_exists(output) #delete if output exists
            arcpy.Project_management(in_dataset, output, matchSR)
            message("File was re-projected and saved as:\n" + output)
            return output
        except:
            message("Warning: spatial reference could not be updated.")
            return in_dataset
    else:
        return in_dataset


def buffer_donut(FC, outFC, buffer_distance):
    """Donut Buffer
    Purpose: Takes inside buffer and creates outside buffers.
             Ensures sort is done on find_ID(), since FID/OID may change.
    Note: Same results as MultipleRingBuffer_analysis(FC, outFC, buf,
          units, "", "None", "OUTSIDE_ONLY") - just faster.
    """
    del_exists(outFC)
    arcpy.Buffer_analysis(FC, outFC, buffer_distance)
    # Make sure it has ID field (should always anyway)
    field = find_ID(FC)
    if not field_exists(outFC, field):
        arcpy.AddField_management(outFC, field)
        
    # Make layer for inner area to remove
    arcpy.MakeFeatureLayer_management(FC, "lyr")
    sel = "NEW_SELECTION" #selection type

    with arcpy.da.UpdateCursor(outFC, ["SHAPE@", field]) as cursor:
        for buf in cursor:
            # Select FC based on field
            wC = "{} = {}".format(field, buf[1]) #where clause
            arcpy.SelectLayerByAttribute_management("lyr", sel, wC)
            with arcpy.da.SearchCursor("lyr", ["SHAPE@"]) as cursor2:
                for row in cursor2:
                    buf[0] = buf[0].difference(row[0])
            cursor.updateRow(buf)
    return outFC


def buffer_contains(poly, pnts):
    """Buffer Contains
    Purpose: Returns number of points in buffer as list.
    Notes: When a buffer is created for a site it may get a new OBJECT_ID, but
           the site OID@ is maintained as ORIG_FID, buffer OID@ returns the
           new ID. Since results are joined back to the site they must be
           sorted in site order. The outTbl the buffer is created from was
           assigned "orig_ID" which is preffered, then ORIG_FID, then OID@.
    Example: lst = buffer_contains(view_50, addresses).
    """
    ext = get_ext(poly)
    plyOut = os.path.splitext(poly)[0] + "_2" + ext
    del_exists(plyOut) #delete intermediate if it exists
    # Use spatial join to count points in buffers.
    join = "JOIN_ONE_TO_ONE" #one line for each buffer
    match = "INTERSECT" #pnts matched if they intersect target poly
    arcpy.SpatialJoin_analysis(poly, pnts, plyOut, join, "", "", match, "", "")
    # Check for fields to sort with, then "Join_Count" is the number of pnts
    field = find_ID(plyOut)
    lst = field_to_lst(plyOut, [field, "Join_Count"])
    arcpy.Delete_management(plyOut)
    return lst


def find_ID(table):
    """return an ID field where orig_ID > ORIG_FID > OID@
    """
    if field_exists(table, "orig_ID"):
        return "orig_ID"
    elif field_exists(table, "ORIG_FID"):
        return "ORIG_FID"
    else:
        return arcpy.Describe(table).OIDFieldName


def buffer_population(poly, popRast):
    """Buffer Population
    Purpose: Returns sum of raster cells in buffer as list.
    Notes: Currently works on raster of population total (not density)
    Notes: Requires Spatial Analyst (look into rasterstats as alternative?)
           https://pcjericks.github.io/py-gdalogr-cookbook/raster_layers.html
    Notes: Reserved fields are used for Zone Field, which causes problems
           when reading the results table because the new field with counts
           can't have the same name as the reserved field, which is where fld2
           comes into use.
    Notes: If poly has overlapping polygons, the analysis will not be performed
           for each individual polygon, because poly is converted to a raster
           so each location can have only one value.
    """
    lst = []
    tempDBF = poly[:-4]+"_pop.dbf"
    del_exists(tempDBF) #delete intermediate if it exists
    # Make sure Spatial Analyst is available.
    sa_Status = arcpy.CheckOutExtension("Spatial")
    if  sa_Status == "CheckedOut":
        # Check for "orig_ID" then "ORIG_FID" then use OID@
        fld = find_ID(poly)
        arcpy.sa.ZonalStatisticsAsTable(poly, fld, popRast, tempDBF, "", "SUM")
        # check for if fld is a reserved field that would be renamed
        if fld == str(arcpy.Describe(poly).OIDFieldName):
            fld2 = fld + "_" #hoping the assignment is consistent
        else: fld2 = fld
        
        lst = field_to_lst(tempDBF, [fld2, "SUM"]) #"AREA" "OID" "COUNT"
        arcpy.Delete_management(tempDBF)
    else:
        message("Spatial Analyst is " + sa_Status)
        message("Population in area could not be estimated.")
    return lst


def percent_cover(poly, bufPoly, units = "SQUAREMETERS"):
    """Percent Cover
    Purpose:"""
    arcpy.MakeFeatureLayer_management(poly, "polyLyr")
    lst=[]
    orderLst=[]
    #add handle for when no overlap?
    # Check for "orig_ID" then "ORIG_FID" then use OID@
    field = find_ID(bufPoly)
    with arcpy.da.SearchCursor(bufPoly, ["SHAPE@", field]) as cursor:
        for row in cursor:
            totalArea = dec(row[0].getArea("PLANAR", units))
            match = "INTERSECT" # Default
            arcpy.SelectLayerByLocation_management("polyLyr", match, row[0])
            lyrLst = []
            with arcpy.da.SearchCursor("polyLyr", ["SHAPE@"]) as cursor2:
                for row2 in cursor2:
                    p = 4 #dimension = polygon
                    interPoly = row2[0].intersect(row[0], p)
                    interArea = dec(interPoly.getArea("PLANAR", units))
                    lyrLst.append((interArea/totalArea)*100)
            lst.append(sum(lyrLst))
            orderLst.append(row[1])
    arcpy.Delete_management("polyLyr")
    # Sort by ID field
    orderLst, lst = (list(x) for x in zip(*sorted(zip(orderLst, lst))))
    return lst
        

def list_buffer(lyr, field, lyr_range):
    """List in buffer
    Purpose: generates a list of catchments in buffer"""
    arcpy.SelectLayerByAttribute_management(lyr, "CLEAR_SELECTION")
    arcpy.SelectLayerByLocation_management(lyr, "INTERSECT", lyr_range)
    HUC_ID_lst = field_to_lst(lyr, field) #list catchment IDs
    return (HUC_ID_lst)


def selectStr_by_list(field, lst):
    """Selection Query String from list
    Purpose: return a string for a where clause from a list of field values
    """
    exp = ''
    for item in lst:
        if type(item) in [str, unicode]: #sequence
            exp += "{} = '{}' OR ".format(field, item)
        elif type(item) == float:
            exp += '"{}" = {} OR '.format(field, dec(item))
        elif type(item) in [int, long, complex]: #numeric
            exp += '"{}" = {} OR '.format(field, item)
        else:
            message("'{}' in list, unknown type '{}'".format(item, type(item)))
    return (exp[:-4])


def field_to_lst(table, field):
    """Read Field to List
    Purpose:
    Notes: if field is: string, 1 field at a time;
                        list, 1 field at a time or 1st field is used to sort
    Example: lst = field_to_lst("table.shp", "fieldName")
    """
    lst = []
    if type(field) == list:
        if len(field) == 1:
            field = field[0]
        elif len(field) > 1:
            # First field is used to sort, second field returned as list
            order = []
            # Check for fields in table
            if field_exists(table, field[0]) and field_exists(table, field[1]):
                with arcpy.da.SearchCursor(table, field) as cursor:
                    for row in cursor:
                        order.append(row[0])
                        lst.append(row[1])
                order, lst = (list(x) for x in zip(*sorted(zip(order, lst))))
                return lst
            else:
                message(str(field) + " could not be found in " + str(table))
                message("Empty values will be returned.")
        else:
            message("Something went wrong with the field to list function")
            message("Empty values will be returned.")
            return []
    if type(field) == str:
        # Check that field exists in table
        if field_exists(table, field) == True:
            with arcpy.da.SearchCursor(table, [field]) as cursor:
                for row in cursor:
                    lst.append(row[0])
            return lst
        else:
            message(str(field) + " could not be found in " + str(table))
            message("Empty values will be returned.")
    else:
        message("Something went wrong with the field to list function")

def lst_to_field(table, field, lst): #handle empty list
    """Add List to Field
    Purpose:
    Notes: 1 field at a time
    Example: lst_to_field(featureClass, "fieldName", lst)
    """
    if len(lst) ==0:
        message("No values to add to '{}'.".format(field))
    else:
        with arcpy.da.UpdateCursor(table, [field]) as cursor:
            #for row in cursor:
            for i, row in enumerate(cursor):
                    row[0] = lst[i]
                    cursor.updateRow(row)


def lst_to_AddField_lst(table, field_lst, list_lst, type_lst):
    """Lists to ADD Field
    Purpose:
    Notes: Table, list of new fields, list of listes of field values,
           list of field datatypes.
    """
    if len(field_lst) != len(list_lst) or len(field_lst) != len(type_lst):
        message("ERROR: lists aren't the same length!")
    #"" defaults to "DOUBLE"
    type_lst = ["Double" if x == "" else x for x in type_lst]

    for i, field in enumerate(field_lst):
        #add fields
        arcpy.AddField_management(table, field, type_lst[i])
        #add values
        lst_to_field(table, field, list_lst[i])


def unique_values(table, field):
    """Unique Values
    Purpose: returns a sorted list of unique values
    Notes: used to find unique field values in table column
    """
    with arcpy.da.SearchCursor(table, [field]) as cursor:
        return sorted({row[0] for row in cursor if row[0]})


def buffer_contains_multiset(dataset1, dataset2, bufferFC):
    """make qual list based on 2 datasets"""
    lst = []
    if dataset1 is not None:
        # Dataset in buffer?
        lst_1 = buffer_contains(bufferFC, dataset1)
        if dataset2 is not None:
            # Dataset2 in buffer?
            lst_2 = buffer_contains(bufferFC, dataset2)
            for i, item in enumerate(lst_1):
                if 0 in [item, lst_2[i]]:
                    lst.append("NO")
                else:
                    lst.append("YES")
            return lst
        else:
            return quant_to_qual_lst(lst_1)
    elif dataset2 is not None:
        lst_2 = buffer_contains(bufferFC, dataset2)
        return quant_to_qual_lst(lst_2)
    else:
        return lst
                    

def quant_to_qual_lst(lst):
    """Quantitative List to Qualitative List
    Purpose: convert counts of >0 to YES"""
    qual_lst = []
    for i in lst:
        if (i == 0):
            qual_lst.append("NO")
        else:
            qual_lst.append("YES")
    return qual_lst


###########MODULES############
def FR_MODULE(PARAMS):
    """Flood Risk Benefits"""
    start1 = time.clock() #start the clock (full module)
    start = time.clock() #start the clock (parts)
    mod_str = "Flood Risk Reduction Benefits analysis"
    message(mod_str + "...")

    addresses, popRast = PARAMS[0], PARAMS[1]
    flood_zone = PARAMS[2]
    OriWetlands, subs = PARAMS[3], PARAMS[4]
    Catchment, InputField, Flow = PARAMS[5], PARAMS[6], PARAMS[7]
    outTbl = PARAMS[8]

    path = os.path.dirname(outTbl) + os.sep
    ext = get_ext(outTbl)

    # Check for "orig_ID" then "ORIG_FID" then use OID@
    OID_field = find_ID(outTbl)

    # Naming convention for flood intermediates
    FA = path + "temp_FloodArea_" 
    # Name intermediate files
    assets = FA + "_assets" + ext #addresses/population in flood zone
    fld_A1 = FA + "1_buffer" + ext #buffers
    fld_A2 = FA + "2_zone" + ext #flood zone in buffer
    fld_A3_clip = FA + "3_clip" + ext #downstream of a site
    # Single site's downstream area dissolved to one row
    fld_A3_clip_1 = FA + "3_single" + ext
    # Feature Class to append single rows to 
    cName = os.path.basename(FA) + "3_down" + ext
    fld_A3_down = path + cName
            
    start=exec_time(start, "intiating variables for " + mod_str)

    # Check NHD+ inputs
    nhd_ck = nhdPlus_check(Catchment, InputField, Flow)
    if not nhd_ck:
        message("Flood benefits will not be assessed")
    else: #assign defaults via nhdPlus_check()
        Catchment, InputField, Flow = nhd_ck
    
    # Check that there are assets in the flood zone.
    if flood_zone is not None:
        # check spatial ref
        flood_zone = checkSpatialReference(outTbl, flood_zone)
        if addresses is not None: #if using addresses
            del_exists(assets)
            arcpy.Clip_analysis(addresses, flood_zone, assets)
            total_cnt = arcpy.GetCount_management(assets) #count addresses
            # If there are no addresses in flood zones stop analysis.
            if int(total_cnt.getOutput(0)) <= 0:
                arcpy.AddError("No addresses within the flood area.")
                print("No addresses within the flooded area.")
                raise arcpy.ExecuteError
        elif popRast is not None: #NOT YET TESTED
            geo = "ClippingGeometry" #use geometry of flood_zone to clip
            e = "NO_MAINTAIN_EXTENT" #maintain cells, no resampling
            del_exists(assets)
            arcpy.Clip_management(popRast, "", assets, flood_zone, "", geo, e)
            # If there are no people in flood zones stop analysis
            m = "MAXIMUM"
            rMax = arcpy.GetRasterProperties_management(assets, m).getOutput(0)
            if rMax <= 0:
                arcpy.AddError("Nothing to do with input raster yet")
                print("Nothing to do with input raster yet")
                raise arcpy.ExecuteError
    else:
        if addresses is not None:
            assets = addresses
        elif popRast is not None:
            assets = popRast
        message("WARNING: No flood zone entered, results will be analyzed" +
                " using the complete area instead of just areas that flood.")

    # Buffer each site by 2.5 mile radius
    del_exists(fld_A1)
    arcpy.Buffer_analysis(outTbl, fld_A1, "2.5 Miles")
    # Clip the buffer to flood polygon
    message("Reducing flood zone to 2.5 Miles from sites...")
    if flood_zone is not None:
        del_exists(fld_A2)
        arcpy.Clip_analysis(fld_A1, flood_zone, fld_A2)
    else:
        fld_A2 = fld_A1
        
    # Clip the buffered flood area to downstream basins
    #MAKE OPTIONAL? if Catchment is not None: 
    message("Determining downstream flood zone area from:\n" + Catchment)

    arcpy.MakeFeatureLayer_management(fld_A1, "buffer")
    arcpy.MakeFeatureLayer_management(fld_A2, "flood_lyr")
    arcpy.MakeFeatureLayer_management(Catchment, "catchment")

    UpCOMs, DownCOMs = setNHD_dict(Flow) #REDUCE TO DownCOMs ONLY

    # Create empty FC for downstream catchments
    del_exists(fld_A3_down)
    spatial_reference = "flood_lyr"
    p = "POLYGON"
    arcpy.CreateFeatureclass_management(path, cName, p, spatial_reference)
    if field_exists(fld_A3_down, OID_field) == False: #Add OID field
        arcpy.AddField_management(fld_A3_down, OID_field, "LONG")

    site_cnt = arcpy.GetCount_management(outTbl)
    sel = "NEW_SELECTION"
    with arcpy.da.SearchCursor(outTbl, ["SHAPE@", OID_field]) as cursor:
        for site in cursor:
            # Select buffer for site
            wClause = "{} = {}".format(OID_field, site[1])
            arcpy.SelectLayerByAttribute_management("buffer", sel, wClause)
            
            # List catchments in buffer
            bufferCatchments = list_buffer("catchment", InputField, "buffer")

            # Subset DownCOMs to only those in buffer (helps limit coast)
            shortDownCOMs = defaultdict(list)
            for i in bufferCatchments:
                shortDownCOMs[i].append(DownCOMs[i])
                shortDownCOMs[i] = list(chain.from_iterable(shortDownCOMs[i]))

            # Select catchment(s) where the restoration site overlaps
            oTyp = "INTERSECT" #overlap type
            arcpy.SelectLayerByLocation_management("catchment", oTyp, site[0])

            # List catchments downstream selection
            downCatch = list_downstream("catchment", InputField, shortDownCOMs)
            # Catchments in both downCatch and bufferCatchments
            catchment_lst = list(set(downCatch).intersection(bufferCatchments))
            # SELECT downstream catchments in buffer
            #Redundant- the last catchment will already be outside the buffer
            qryDown = selectStr_by_list(InputField, catchment_lst)
            arcpy.SelectLayerByAttribute_management("catchment", sel, qryDown)
            #MAY need to dissolve selection into single FC for popRaster
            #arcpy.Dissolve_management("catchment", fld_A3_clip_1)

            # Select and clip corresponding flood zone to catchments
            arcpy.SelectLayerByAttribute_management("flood_lyr", sel, wClause)
            arcpy.Clip_analysis("flood_lyr", "catchment", fld_A3_clip)
            arcpy.MakeFeatureLayer_management(fld_A3_clip, "fZone_down")
            # Dissolve down to one row
            arcpy.Dissolve_management("fZone_down", fld_A3_clip_1, OID_field) 
            # Append single row to empty clipped set
            arcpy.Append_management(fld_A3_clip_1, fld_A3_down, "NO_TEST")
            clip_rows = arcpy.GetCount_management(fld_A3_down)
            message("Determined catchments downstream for site " +
                    "{}, of {}".format(clip_rows, site_cnt))

    message("Finished reducing flood zone areas to downstream from sites...")

    #3.2 Calculate flood area as benefitting percentage
    message("Measuring flood zone area downstream of each site...")
    aD = "areaD" #area of flood zone downstream

    # Add/calculate fields for flood
    arcpy.AddField_management(fld_A2, "area", "Double")
    arcpy.AddField_management(fld_A2, "area_pct", "Double")
    exprs = "!SHAPE.area!" #sql expression
    py_exp = "PYTHON_9.3" #python expression method
    arcpy.CalculateField_management(fld_A2, "area", exprs, py_exp, "")
    arcpy.AddField_management(fld_A2, "areaD_pct", "Double")

    # Add/calculate fields for downstream flood zone
    arcpy.AddField_management(fld_A3_down, aD, "Double")
    arcpy.CalculateField_management(fld_A3_down, aD, exprs, py_exp, "")

    # Move downstream area result to flood zone table
    arcpy.JoinField_management(fld_A2, OID_field, fld_A3_down, OID_field, [aD])

    #3.2 Calculate percent area fields
    with arcpy.da.UpdateCursor(fld_A2, ["area_pct", "area", "BUFF_DIST",
                                             "areaD_pct", aD]) as cursor:
        # BUFF_DIST is in datum units (better for area calculation than 25 mi2)
        #if fields_exists(wetlands, BUFF_DIST) it is renamed by index in fld_A2
        for row in cursor:
            # Percent of area (2.5 mile radius) that is flood zone
            row[0] = row[1]/(math.pi*((row[2]**2.0)))
            if row[4] is not None:
                # Percent of flood zone in range that is downstream of site
                row[3] = row[4]/row[1]
            cursor.updateRow(row)
    # Extract results to lists
    lst_floodzoneArea_pct = field_to_lst(fld_A2, "area_pct")
    lst_floodzoneD = field_to_lst(fld_A2, aD)
    lst_floodzoneD_pct = field_to_lst(fld_A2, "areaD_pct")

    #3.2 Calculate number of people benefitting
    message("Counting people who benefit...")
    if addresses is not None:
        # Addresses in buffer/flood zone/downstream.
        lst_flood_cnt = buffer_contains(str(fld_A3_down), assets)

    elif popRast is not None: #NOT TESTED
        # Population in buffer/flood zone/downstream 
        lst_flood_cnt = buffer_population(fld_A3_down, popRast)
        
    start=exec_time(start, mod_str + ": 3.2 How Many Benefit")

    # 3.3.A: SERVICE QUALITY
    message("Measuring area of each restoration site...")

    # Calculate area of each restoration site
    siteAreaLst =[]
    with arcpy.da.SearchCursor(outTbl, ["SHAPE@"]) as cursor:
        for row in cursor:
            siteAreaLst.append(row[0].getArea("GEODESIC", "ACRES"))

    start = exec_time (start, mod_str + ": 3.3.A Service Quality")

    # 3.3.B: SUBSTITUTES
    if subs is not None:
        message("Estimating number of substitutes within 2.5 miles " +
                "downstream of restoration site...")
        subs = checkSpatialReference(outTbl, subs)

        # Subs in buffer/flood/downstream
        lst_subs_cnt = buffer_contains(str(fld_A3_down), subs)

        # Convert lst to binary list
        lst_subs_cnt_boolean = quant_to_qual_lst(lst_subs_cnt)

        start = exec_time (start, mod_str + ": 3.3.B Scarcity " +
                           "(substitutes - 'FR_3B_boo')")
    else:
        message("No Substitutes (dams and levees) specified, 'FR_sub' will" +
                " all be '0' and 'FR_3B_boo' will be left blank.")
        lst_subs_cnt, lst_subs_cnt_boolean = [], []
            
    #3.3.B: SCARCITY
    # This uses the complete buffer (fld_A1), alternatively,
    #this could be restricted to the flood zone or upstream/downstream.
    if OriWetlands is not None:
        message("Estimating area of wetlands within 2.5 miles in both " +
                "directions (5 miles total) of restoration sites...")

        lst_floodRet_Density = percent_cover(OriWetlands, fld_A1)
        start = exec_time (start, mod_str + ": Scarcity ('FR_3B_sca')")
    else:
        message("Substitutes (existing wetlands) input not specified, " +
                "'FR_3B_sca' will all be '0'.")
        lst_floodRet_Density = []
        
    #FINAL STEP: move results to results file
    fields_lst = ["FR_2_cnt", "FR_zPct", "FR_zDown", "FR_zDoPct", "FR_3A_acr",
                  "FR_3A_boo", "FR_sub", "FR_3B_boo", "FR_3B_sca", "FR_3D_boo"]
    list_lst = [lst_flood_cnt, lst_floodzoneArea_pct, lst_floodzoneD,
                lst_floodzoneD_pct, siteAreaLst, [], lst_subs_cnt,
                lst_subs_cnt_boolean, lst_floodRet_Density, []]
    type_lst = ["", "", "", "", "", "Text", "", "Text", "", "Text"]

    lst_to_AddField_lst(outTbl, fields_lst, list_lst, type_lst)

    #cleanup
    deleteFC_Lst([fld_A3_clip_1, fld_A3_clip, str(fld_A3_down),
                  fld_A2, fld_A1, assets])
    deleteFC_Lst(["flood_zone_lyr", "flood_zone_down_lyr", "catchment",
                  "polyLyr", "buffer"])
                                       
    message(mod_str + " Module Complete")
    start1=exec_time(start1, "full flood module")


##############################
def NHD_get_MODULE(PARAMS):
    """Download NHD Plus Data"""
    
    sites = PARAMS[0]
    NHD_VUB = PARAMS[1]
    local = PARAMS[2]

    # Assign default destination if not user specified
    script_dir = os.path.dirname(os.path.realpath(__file__))
    if os.path.basename(script_dir) == 'py_standaloneScripts':
        # Move up one folder if standalone script
        script_dir = os.path.dirname(script_dir) + os.sep
    else:
        script_dir = script_dir + os.sep
    if local is None:
        local = script_dir + "NHDPlusV21"
        message("Files will be Downloaded to default location:\n" + local)
    else:
        message("Files will be Downloaded to user location:\n" + local)

    # Default file location to copy downloads to
    local_gdb = local + os.sep + "NHDPlus_Downloads.gdb"
    if os.path.isdir(local_gdb) and get_ext(local_gdb) == ".gdb":
        message("Downloaded files will be added to default file geodatabase")
    else:
        message("Unable to find Default file geodatabase:\n" + local_gdb)
        message("Files will be downloaded but must be combined manually.")
        
    # Assign default boundary file if not user specified
    if NHD_VUB is None:
        NHD_VUB = script_dir + "NHDPlusV21" + os.sep + "BoundaryUnit.shp"
        loc = "default location:\n" + NHD_VUB
    else:
        loc = "user specified location:\n" + NHD_VUB

    # Check boundary file
    if arcpy.Exists(NHD_VUB):
            message("NHDPlus Boundaries found in " + loc)
    else:
        arcpy.AddError("NHDPlus Boundaries could not be found in " + loc)
        print("NHDPlus Boundaries could not be found in " + loc)
        raise arcpy.ExecuteError

    # Check projection.
    if get_ext(local) == '.gdb': #filename if re-projected in geodatabase
        out_prj = local + os.sep + 'VUB_prj'
    else: #filename if re-projected in folder
        out_prj = local + os.sep + 'VUB_prj.shp'
    NHD_VUB = checkSpatialReference(sites, NHD_VUB, out_prj)

    # Select NHDPlus vector unit boundaries
    arcpy.MakeFeatureLayer_management(NHD_VUB, "VUB") #make layer.
    overlap = "WITHIN_A_DISTANCE"
    dis = "5 Miles" #distance within
    arcpy.SelectLayerByLocation_management("VUB", overlap, sites, dis, "", "")

    # http://www.horizon-systems.com/NHDPlusData/NHDPlusV21/Data/NHDPlus
    sub_link = "/{0}Data/{0}V21/Data/{0}".format("NHDPlus")
    NHD_http = "http://www.horizon-systems.com" + sub_link
    
    # Gather info from fields to construct request
    ID_list = field_to_lst("VUB", "UnitID")
    d_list = field_to_lst("VUB", "DrainageID")

    for i, DA in enumerate(d_list):
        # Give progress update
        message("Downloading region {} of {}".format(str(i+1), len(d_list)))

        # Zipfile names
        ID = ID_list[i]
        ext = ".7z"

        # Componentname is the name of the NHDPlusV2 component in the file
        f_comp = "NHDPlusCatchment"
        ff_comp = "NHDPlusAttributes"
        
        # Some Zipfiles had different vv, data content versions
        f_vv = "01" #Catchments
        if ID == "06":
            f_vv = "05"
        if ID in ['10U', '13', '17']:
            f_vv = "02"
            
        ff_vv = "01" #Attributes
        if ID in ["20", "21", "22AS", "22GU", "22MP"]:
            ff_vv = "02"
        if ID in ["03N", "03S", "03W", "13", "16"]:
            ff_vv = "05"
        if ID in ["02", "09", "11", "18"]:
            ff_vv = "06"
        if ID in ["01", "08", "12"]:
            ff_vv = "07"
        if ID in ["05", "15", "17"]:
            ff_vv = "08"
        if ID in ["06", "07", "10U", "14"]:
            ff_vv = "09"
        if ID == "10L":
            ff_vv = "11" 
        if ID == "04":
            ff_vv = "12"
            
        # Set http zipfile is requested from
        if DA in ["SA", "MS", "CO", "PI"]: #regions with sub-regions
            request = NHD_http + DA + "/" + "NHDPlus" + ID + "/"
        else:
            request = NHD_http + DA + "/"

        # Download child destination folder
        ID_folder = local + os.sep + "NHDPlus" + DA + os.sep + "NHDPlus" + ID

        # Assign catchment filenames
        f = "NHDPlusV21_{}_{}_{}_{}{}".format(DA, ID, f_comp, f_vv, ext)
        # Fix the one they mis-named
        if ID == "04":
            f = f[:-6] + "s_05.7z"
        # Download catchment
        HTTP_download(request, local, f)
        # unzip catchment file using winzip
        WinZip_unzip(local, f)
        # Pull catchments into gdb
        cat_folder = ID_folder + os.sep + f_comp
        cat_shp = cat_folder + os.sep + "Catchment.shp"
        local_catchment = local_gdb + os.sep + "Catchment"
        append_to_default(local_catchment, cat_shp, "catchment")

        # Assign flow table filename
        flow_f = "NHDPlusV21_{}_{}_{}_{}{}".format(DA, ID, ff_comp, ff_vv, ext)
        # Download flow table
        HTTP_download(request, local, flow_f)
        # unzip flow table using winzip
        WinZip_unzip(local, flow_f)
        # Pull flow table into gdb
        flow_folder = ID_folder + os.sep + ff_comp
        flow_dbf = flow_folder + os.sep + "PlusFlow.dbf"
        local_flow = local_gdb + os.sep + "PlusFlow"
        append_to_default(local_flow, flow_dbf, "flow table")

##############################
def View_MODULE(PARAMS):
    """Scenic View Benefits"""
    start1 = time.clock() #start the clock
    mod_str = "Scenic View Benefits analysis"
    message(mod_str + "...")

    addresses, popRast = PARAMS[0], PARAMS[1]
    trails, roads = PARAMS[2], PARAMS[3]
    wetlandsOri = PARAMS[4]
    landuse = PARAMS[5]
    field, fieldLst = PARAMS[6], PARAMS[7]
    outTbl = PARAMS[8]

    path = os.path.dirname(outTbl) + os.sep
    ext = get_ext(outTbl)

    # Set variables
    vUnit = "Meters"
    VA = path + "int_ViewArea" #naming convention for view intermediates
    view50, view100 = VA + "_50" + ext, VA + "_100" + ext #50 and 100m buffers
    view100_int =  VA + "_100int" + ext
    view200 = VA + "_200" + ext #200m buffer
    wetlands_dis = path + "wetland_dis" + ext #wetlands dissolved

    start = time.clock() #start the clock

    # 2 How Many Benefit
    step_str = "3.2 How Many Benefit?"
    message(mod_str + " - " + step_str)

    # Create buffers
    del_exists(view50)
    arcpy.Buffer_analysis(outTbl, view50, "50 Meters") #buffer sites by 50m
    buffer_donut(view50, view100, "50 Meters") #distance past original buffer
    
    # Calculate number benefitting in buffers
    if addresses is not None: #address based method
        lst_view50 = buffer_contains(view50, addresses)
        lst_view100 = buffer_contains(view100, addresses)
        msg = mod_str + "{} - {} (from addresses)".format(mod_str, step_str)
        start=exec_time(start, msg)
        #cleanup
        arcpy.Delete_management(view50)
        arcpy.Delete_management(view100)
        
    elif popRast is not None: #population based method
        lst_view50 = buffer_population(view50, popRast)
        lst_view100 = buffer_population(view100, popRast)
        msg = "{} - {} (from population raster)".format(mod_str, step_str)
        start=exec_time(start, msg)

    # Calculate weighted scores
    lst_view_score = view_score(lst_view50, lst_view100) 

    # Generate a complete 100m buffer and determine if trails/roads interstect
    del_exists(view100_int)
    arcpy.Buffer_analysis(outTbl, view100_int, "100 Meters")
    # Generate a Yes/No list from trails and roads
    if trails is not None or roads is not None:
        rteLst = buffer_contains_multiset(trails, roads, view100_int)
    else:
        message("No roads or trails specified")

    msg =  "{} - {} (from trails or roads)".format(mod_str, step_str)
    start=exec_time(start, msg)
    start1= exec_time(start1, "{} - {} Total".format(mod_str, step_str))

    # 3.B Substitutes/Scarcity
    message(mod_str + " - 3.B Scarcity")
    if wetlandsOri is not None: 
        # Make a 200m buffer that doesn't include the site                      
        buffer_donut(outTbl, view200, "200 Meters")

    #FIX next line?
        #may require lyr input
        arcpy.Dissolve_management(wetlandsOri, wetlands_dis)
        wetlandsOri = wetlands_dis
        #wetlands in 200m
        lst_view_Density = percent_cover(wetlandsOri, view200)
    else:
        message("No existing wetlands input specified")
        lst_view_Density = []
    start=exec_time(start, mod_str + ": 3.3B Scarcity")

    # 3.C Complements
    message(mod_str + " - 3.C Complements") #PARAMS[landUse, fieldLst, field]

    if landuse is not None:
        arcpy.MakeFeatureLayer_management(landuse, "lyr")
        #construct query from field list
        whereClause = selectStr_by_list(field, fieldLst)
        sel = "NEW_SELECTION"
        # reduce to desired LU
        arcpy.SelectLayerByAttribute_management("lyr", sel, whereClause)
        landUse2 = os.path.splitext(outTbl)[0] + "_comp" + ext
        del_exists(landUse2)
        arcpy.Dissolve_management("lyr", landUse2, field) #reduce to unique

        #number of unique LU in LU list which intersect each buffer
        lst_comp = buffer_contains(view200, landUse2)
        start=exec_time(start, mod_str + ": 3.3C Complements")
    else:
        message("No land use input specified")
        lst_comp = []

    message("Saving Scenic View Benefits results to Output...")
    #FINAL STEP: move results to results file
    fields_lst = ["V_2_50", "V_2_100", "V_2_score", "V_2_boo",
                  "V_3A_boo", "V_3B_scar", "V_3C_comp", "V_3D_boo"]
    list_lst = [lst_view50, lst_view100, lst_view_score, rteLst,
                [], lst_view_Density, lst_comp, []]
    type_lst = ["", "", "", "Text", "Text", "", "", "Text"]

    lst_to_AddField_lst(outTbl, fields_lst, list_lst, type_lst)

    # Cleanup FC, then lyrs
    #deleteFC_Lst([100int, 200sp, wetland_dis?])
    
    message("{} Complete".format(mod_str))

##############################
############ENV EDU###########
def Edu_MODULE(PARAMS):
    """ Environmental Education Benefits"""
    start = time.clock() #start the clock
    mod_str = "Environmental Education Benefits analysis"
    message(mod_str + "...")
    
    edu_inst = PARAMS[0]
    wetlandsOri = PARAMS[1]
    outTbl = PARAMS[2]

    path = os.path.dirname(outTbl) + os.sep
    ext = get_ext(outTbl)

    #set variables
    eduArea = path + "eduArea" + ext
    edu_2 = path + "edu_2" + ext #buffer 1/2 mile

    #3.2 - NUMBER WHO BENEFIT 
    start1 = time.clock() #start the clock
    message(mod_str + " - 3.2 How Many benefit?") 
    if edu_inst is not None:
        edu_inst = checkSpatialReference(outTbl, edu_inst) #check spatial ref
        # Buffer each site by 0.25 miles
        
        arcpy.Buffer_analysis(outTbl , eduArea, "0.25 Miles")
        #list how many schools in buffer
        lst_edu_cnt = buffer_contains(eduArea, edu_inst)
    else:
        message("No educational institutions specified")
        lst_edu_cnt = []
    start=exec_time(start, mod_str + " - 3.2 How Many benefit (institutions)")

    #3.3.B - Scarcity
    message("Environmental Education analysis - 3.3B Scarcity")
    if wetlandsOri is not None:
        arcpy.Buffer_analysis(outTbl, edu_2, "0.5 Miles") #not a circle
        #analysis for scarcity
        lst_edu_Density = percent_cover(wetlandsOri, edu_2)
    else:
        message("No pre-existing wetlands specified to determine scarcity")
        lst_edu_Density = []
    start=exec_time(start, mod_str + " - 3.3B Scarcity (existing wetlands)")

    #FINAL STEP: move results to results file
    message("Saving Environmental Education Benefits results to Output...")
    fields_lst = ["EE_2_cnt", "EE_3A_boo", "EE_3B_sca", "EE_3C_boo", "EE_3D_boo"]
    list_lst = [lst_edu_cnt, [], lst_edu_Density, [], []]
    type_lst = ["", "Text", "", "Text", "Text"]

    lst_to_AddField_lst(outTbl, fields_lst, list_lst, type_lst)

    #cleanup FC, then lyrs
    #deleteFC_Lst([eduArea, eduArea_2?, edu_2])

    message(mod_str + " Complete")
    
##############################
##############REC#############
def Rec_MODULE(PARAMS):
    """Recreation Benefits"""
    start1 = time.clock() #start the clock
    mod_str = "Recreation Benefits analysis"
    message(mod_str + "...")
    
    addresses, popRast = PARAMS[0], PARAMS[1]
    trails, bus_Stp = PARAMS[2], PARAMS[3]
    wetlandsOri = PARAMS[4]
    landuse = PARAMS[5]
    field, fieldLst = PARAMS[6], PARAMS[7]
    outTbl = PARAMS[8]

    path = os.path.dirname(outTbl) + os.sep
    ext = get_ext(outTbl)

    #set variables
    recArea = path + "recArea"
    #buffer names
    rec_500m, rec_1000m = recArea + "_03mi" + ext, recArea + "_05mi" + ext
    rec_10000m = recArea + "_6mi" + ext
    #scarcity buffer names
    rec_06, rec_1, = recArea + "_Add_06mi" + ext, recArea + "_Add_1mi" + ext
    rec12 = recArea + "_Add_12mi" + ext
    #dissolved landuse
    landuseTEMP = path + "landuse_temp" + ext

    #3.2 - NUMBER WHO BENEFIT
    message(mod_str + " - 3.2 How Many Benefit")
    start = time.clock() #start the clock
    #3.2 - A: buffer each site by 500m, 1km, and 10km
    arcpy.Buffer_analysis(outTbl , rec_500m, "0.333333 Miles")
    #buffer_donut(rec_500m, rec_1000m, [0.166667], "Miles")
    arcpy.Buffer_analysis(outTbl , rec_1000m, "0.5 Miles")
    buffer_donut(rec_1000m , rec_10000m, "5.5 Miles")

    #3.2 - B: overlay population
    if addresses is not None: #address based method
        lst_rec_cnt_03 = buffer_contains(rec_500m, addresses)
        lst_rec_cnt_05 = buffer_contains(rec_1000m, addresses)
        lst_rec_cnt_6 = buffer_contains(rec_10000m, addresses)

        msg = "{} - 3.2 How Many Benefit? (from addresses)".format(mod_str)
        start=exec_time(start, msg)

    elif popRast is not None: #check for population raster
        lst_rec_cnt_03 = buffer_population(rec_500m, popRast)
        lst_rec_cnt_05 = buffer_population(rec_1000m, popRast)
        lst_rec_cnt_6 = buffer_population(rec_10000m, popRast)

        msg = "{} - 3.2 How Many Benefit? (raster population)".format(mod_str)
        start=exec_time(start, msg)
    else: #this should never happen
        message("Neither addresses or a population raster were found.")
        lst_rec_cnt_03 = []
        lst_rec_cnt_05 = []
        lst_rec_cnt_6 = []

    #3.2 - C: overlay trails
    rteLst_rec_trails = []
    if trails is not None:
        lst_rec_trails = buffer_contains(rec_500m, trails) #bike trails in 500m
        rteLst_rec_trails = quant_to_qual_lst(lst_rec_trails) #present = YES
    else:
        message("No trails specified for determining if there are bike " +
                "paths within 1/3 mi of site (R_2_03_tb)")
        lst_rec_trails = []
        rteLst_rec_trails = []
        
    #3.2 - C2: overlay bus stops
    rteLst_rec_bus = []
    if bus_Stp is not None:
        bus_Stp = checkSpatialReference(outTbl, bus_Stp) #check projections
        lst_rec_bus = buffer_contains(rec_500m, bus_Stp) #bus stops in 500m
        rteLst_rec_bus = quant_to_qual_lst(lst_rec_bus) #if there are = YES
    else:
        message("No bus stops specified for determining if there are bus " +
                "stops within 1/3 mi of site (R_2_03_bb)")
        lst_rec_bus = []
        rteLst_rec_bus = []
    msg =  "{}: 3.2 How Many Benefit?".format(mod_str)
    start=exec_time(start, msg + "(from trails or bus)")
    start1=exec_time(start1, msg)

    #3.3.A SERVICE QUALITY - Total area of green space around site ("R_3A_acr")
    message(mod_str + " - 3.3.A Service Quality")
    lst_green_neighbor = []
    if landuse is not None:
        #reduce to desired LU
        #arcpy.MakeFeatureLayer_management(landuse, "lyr")
        wClause = selectStr_by_list(field, fieldLst)
        #arcpy.SelectLayerByAttribute_management("lyr", "NEW_SELECTION", whereClause)
        #arcpy.Dissolve_management("lyr", landuseTEMP, "", "", "SINGLE_PART")
        name = os.path.basename(landuseTEMP)
        arcpy.FeatureClassToFeatureClass_conversion(landuse, path, name, wClause)
        #make into selectable layer    
        arcpy.MakeFeatureLayer_management(landuseTEMP, "greenLyr")

        with arcpy.da.SearchCursor(outTbl, ["SHAPE@"]) as cursor:
            for site in cursor: #for each site
                # Atart with site area
                var = dec(site[0].getArea("PLANAR", "ACRES"))
                #select green space that intersects the site
                oTyp = "INTERSECT"
                arcpy.SelectLayerByLocation_management("greenLyr", oTyp, site[0])
                with arcpy.da.SearchCursor("greenLyr", ["SHAPE@"]) as cursor2:
                    for row in cursor2:
                        #area of greenspace
                        areaGreen = dec(row[0].getArea("PLANAR", "ACRES"))
                        #part of greenspace already in site
                        overlap = site[0].intersect(row[0], 4)
                        #area of greenspace already in site
                        interArea = dec(overlap.getArea("PLANAR", "ACRES"))
                        #add area of greenspace - overlap to site and previous rows
                        var += areaGreen - interArea
                lst_green_neighbor.append(var)
    else:
        message("No landuse specified for determining area of green space " +
                "around site (R_3A_acr)")

    start=exec_time(start, "{}: 3.3.A Service Quality".format(mod_str))

    #3.3.B SCARCITY - green space within 2/3 mi, 1 mi and 12 mi of site
    message(mod_str + " - 3.3.B Scarcity")
    if landuse is not None or wetlandsOri is not None:
        #sub are greenspace or wetlands?
        if landuse is not None:
            subs = landuseTEMP
        else:
            if wetlandsOri is not None:
                subs = wetlandsOri
                message("No landuse input specified, existing wetlands used " +
                        "for scarcity instead")

        #buffer each site by double original buffer
        arcpy.Buffer_analysis(outTbl, rec_06, "0.666666 Miles")
        arcpy.Buffer_analysis(outTbl, rec_1, "1 Miles")
        arcpy.Buffer_analysis(outTbl, rec12, "12 Miles")
        #overlay buffers with substitutes
        lst_rec_06_Density = percent_cover(subs, rec_06)
        lst_rec_1_Density = percent_cover(subs, rec_1)
        lst_rec_12_Density = percent_cover(subs, rec12)
    else:
        message("No substitutes (landuse or existing wetlands) inputs " +
                "specified for recreation benefits.")
        lst_rec_06_Density = []
        lst_rec_1_Density = []
        lst_rec_12_Density = []
    start=exec_time(start, mod_str + " - 3.3B Scarcity")

    #Add results from lists
    message("Saving Recreation Benefits results to Output...")    
    fields_lst = ["R_2_03", "R_2_03_tb", "R_2_03_bb", "R_2_05", "R_2_6", "R_3A_acr",
                  "R_3B_sc06", "R_3B_sc1", "R_3B_sc12", "R_3C_boo", "R_3D_boo"]
    list_lst = [lst_rec_cnt_03, rteLst_rec_trails, rteLst_rec_bus,
                lst_rec_cnt_05, lst_rec_cnt_6, lst_green_neighbor,
                lst_rec_06_Density, lst_rec_1_Density, lst_rec_12_Density, [], []]
    type_lst = ["", "Text", "Text", "", "", "", "", "", "", "Text", "Text"]

    lst_to_AddField_lst(outTbl, fields_lst, list_lst, type_lst)

    #cleanup FC, then lyrs
    #deleteFC_Lst([#arcpy.Delete_management(eduArea

    message(mod_str + " complete.")

##############################
#############BIRD#############
def Bird_MODULE(PARAMS):
    """Bird Watching Benefits"""
    start1 = time.clock() #start the clock
    mod_str = "Bird Watching Benefits analysis"
    message(mod_str + "...")

    addresses, popRast = PARAMS[0], PARAMS[1]
    trails, roads = PARAMS[2], PARAMS[3]
    outTbl = PARAMS[4]

    path = os.path.dirname(outTbl) + os.sep
    ext = get_ext(outTbl)

    #set variables
    birdArea = path + "birdArea" + ext

    #3.2 - NUMBER WHO BENEFIT
    start = time.clock()
    message(mod_str + ": 3.2 How Many Benefit?")
     # Buffer each site by 0.2 miles.
    arcpy.Buffer_analysis(outTbl , birdArea, "0.2 Miles")
    if addresses is not None:
        lst_bird_cnt = buffer_contains(birdArea, addresses)
        start=exec_time(start, mod_str +
                        ": 3.2 How Many Benefit? (from addresses)")
    elif popRast is not None:
        lst_bird_cnt = buffer_population(birdArea, popRast)
        start=exec_time(start, mod_str +
                        ": 3.2 How Many Benefit? (from population Raster)")

    #3.2 - are there roads or trails that could see birds on the site?      
    if trails is not None or roads is not None:
        rteLstBird = buffer_contains_multiset(trails, roads, birdArea)
    else:
        message("No trails or roads specified to determine if birds at the " +
                "site will be visible from these")
    start = exec_time(start, mod_str +
                      ": 3.2 How Many Benefit? (from trails or roads)")
    start1 = exec_time(start1, mod_str + ": 3.2 How Many Benefit? Total")
                       
    #Add results from lists
    message("Saving " + mod_str + " results to Output...")
    fields_lst = ["B_2_cnt", "B_2_boo", "B_3A_boo", "B_3C_boo", "B_3D_boo"]
    list_lst = [lst_bird_cnt, rteLstBird, [], [], []]
    type_lst = ["", "Text", "Text", "Text", "Text"]

    lst_to_AddField_lst(outTbl, fields_lst, list_lst, type_lst)

    #cleanup FC, then lyrs
    #deleteFC_Lst([#arcpy.Delete_management(eduArea

    message(mod_str + " complete.")

##############################
##########SOC_EQUITY##########
def socEq_MODULE(PARAMS):
    """Social Equity of Benefits"""
    #start = time.clock() #start the clock
    mod_str = "Social Equity of Benefits analysis"
    message(mod_str + "...")
    
    sovi = PARAMS[0]
    field, SoVI_High = PARAMS[1], PARAMS[2]
    bufferDist = PARAMS[3]
    outTbl = PARAMS[4]

    path = os.path.dirname(outTbl) + os.sep
    ext = get_ext(outTbl)

    #set variables
    #tempPoly = path + "SoviTemp" + ext
    buf = path + "sovi_buffer" + ext

    sovi = checkSpatialReference(outTbl, sovi) #check projection
    
    arcpy.Buffer_analysis(outTbl, buf, bufferDist)

    #select sovi layer by buffer
    arcpy.MakeFeatureLayer_management(sovi, "soviLyr")
    #arcpy.SelectLayerByLocation_management("soviLyr", "INTERSECT", buf)

    #list all the unique values in the specified field
    full_fieldLst = unique_values("soviLyr", field)
    fieldLst = [x for x in full_fieldLst if x not in SoVI_High]

    #add/populate field for SoVI_High
    name = "Vul_High"
    sel = "NEW_SELECTION"
    f_type = "DOUBLE"
    arcpy.AddField_management(outTbl, name, f_type, "", "", "", "", "", "", "")
    wClause = selectStr_by_list(field, SoVI_High)
    arcpy.SelectLayerByAttribute_management("soviLyr", sel, wClause)
    pct_lst = percent_cover("soviLyr", buf)
    lst_to_field(outTbl, name, pct_lst)

    #add fields for the rest of the possible values if 6 or less
    message("There are {} unique values for {}.".format(len(fieldLst), field))
    if len(fieldLst) <6: 
        message("Creating new fields for each...")
        #add fields for each unique in field
        for val in fieldLst:
            name = val.replace(".", "_")[0:9]
            arcpy.AddField_management(outTbl, name, f_type, "", "", "", val,
                                      "", "", "")
            wClause = selectStr_by_list(field, [val])
            arcpy.SelectLayerByAttribute_management("soviLyr", sel, wClause)
            pct_lst = percent_cover("soviLyr", buf)
            lst_to_field(outTbl, name, pct_lst)
    else:
        message("This is too many values to create unique fields for each, " +
                "just calculating {} coverage".format(SoVI_High))

    message(mod_str + " complete.")
    
##############################
#########RELIABILITY##########
def reliability_MODULE(PARAMS):
    """Reliability of Benefits"""
    #start = time.clock() #start the clock
    mod_str = "Reliability of Benefits analysis"
    message(mod_str + "...")
    
    cons_poly = PARAMS[0]
    field = PARAMS[1]
    consLst, threatLst = PARAMS[2], PARAMS[3]
    bufferDist = PARAMS[4]
    outTbl = PARAMS[5]

    path = os.path.dirname(outTbl) + os.sep
    ext = get_ext(outTbl)
    
    #set variables
    buf = path + "conservation" + ext
    
    message("Checking input variables...")
    #remove None from lists
    consLst = [x for x in consLst if x is not None]
    threatLst = [x for x in threatLst if x is not None] #removes 0?
    
    cons_poly = checkSpatialReference(outTbl, cons_poly)
    message("Input variables OK")
    
    #buffer site by user specified distance
    arcpy.Buffer_analysis(outTbl, buf, bufferDist)
    
    #make selection from FC based on fields to include
    sel = "NEW_SELECTION"
    arcpy.MakeFeatureLayer_management(cons_poly, "consLyr")
    whereClause = selectStr_by_list(field, consLst)
    arcpy.SelectLayerByAttribute_management("consLyr", sel, whereClause)
    #determine percent of buffer which is each conservation type
    pct_consLst = percent_cover("consLyr", buf)
    try:
        #make list based on threat use types
        whereThreat = selectStr_by_list(field, threatLst)
        arcpy.SelectLayerByAttribute_management("consLyr", sel, whereThreat)
        pct_threatLst = percent_cover("consLyr", buf)
    except Exception:
        message("Error occured determining percent cover of non-conserved areas.")
        traceback.print_exc()
        pass

    #move results to outTbl
    message("Writing results to 'Conserved' field...")
    fields_lst = ["Conserved", "Threatene"]
    list_lst = [pct_consLst, pct_threatLst]

    lst_to_AddField_lst(outTbl, fields_lst, list_lst, ["", ""])

    message(mod_str + " complete")

##############################
########Report_MODULE#########
def Report_MODULE(PARAMS):
    """Report Generation"""
    start = time.clock() #start the clock
    message("Generating report...")
    #Report_PARAMS = [outTbl, siteName, mxd, pdf]

    outTbl = PARAMS[0]
    siteNameFld = str(PARAMS[1])
    mxd = arcpy.mapping.MapDocument(PARAMS[2])
    #Set file name, ext, and remove file if it already exists
    pdf = PARAMS[3]
    if os.path.splitext(pdf)[1] == "":
        pdf += ".pdf"
    if os.path.exists(pdf):
        os.remove(pdf)
    #Set path for intermediate pdfs
    pdf_path = os.path.dirname(pdf) + os.sep

    #Create the file and append pages in the cursor loop
    pdfDoc = arcpy.mapping.PDFDocumentCreate(pdf)
    
    graphic = "GRAPHIC_ELEMENT"
    blackbox = arcpy.mapping.ListLayoutElements(mxd, graphic, "blackbox")[0]
    graybox = arcpy.mapping.ListLayoutElements(mxd, graphic, "graybox")[0]

    #dictionary for field, type, ltorgt, numDigits, allnos, & average
    fld_dct = {'field': ['FR_2_cnt', 'FR_3A_acr', 'FR_3A_boo', 'FR_3B_boo',
                         'FR_3B_sca', 'FR_3D_boo', 'V_2_50', 'V_2_100',
                         'V_2_score', 'V_2_boo', 'V_3A_boo', 'V_3B_scar',
                         'V_3C_comp', 'V_3D_boo', 'EE_2_cnt', 'EE_3A_boo',
                         'EE_3B_sca', 'EE_3C_boo', 'EE_3D_boo', 'R_2_03', 
                         'R_2_03_tb', 'R_2_03_bb', 'R_2_05', 'R_2_6',
                         'R_3A_acr', 'R_3B_sc06', 'R_3B_sc1', 'R_3B_sc12',
                         'R_3C_boo', 'R_3D_boo', 'B_2_cnt', 'B_2_boo',
                         'B_3A_boo', 'B_3C_boo', 'B_3D_boo', 'Vul_High',
                         'Conserved']}
    txt, dbl ='Text', 'Double'
    fld_dct['type'] = [dbl, dbl, txt, txt, dbl, txt, dbl, dbl, dbl, txt, txt,
                       dbl, dbl, txt, dbl, txt, dbl, txt, txt, dbl, txt,
                       txt, dbl, dbl, dbl, dbl, dbl, dbl, txt, txt, dbl,
                       txt, txt, txt, txt, dbl, dbl]
    fld_dct['ltorgt'] = ['gt', 'gt', '', '', 'lt', '', 'gt', 'gt', 'gt', '', '',
                         'lt', 'gt', '', 'gt', '', 'lt', '', '', 'gt', '',
                         '', 'gt', 'gt', 'gt', 'lt', 'lt', 'lt', '', '', 'gt',
                         '', '', '', '', 'gt', 'gt']
    fld_dct['aveBool'] = ['', '', 'YES', 'NO', '', 'YES', '', '', '', 'YES', 'YES',
                          '', '', 'YES', '', 'YES', '', 'YES', 'YES', '', 'YES',
                          'YES', '', '', '', '', '', '', 'YES', 'YES', '',
                          'YES', 'YES', 'YES', 'YES', '', '']
    fld_dct['numDigits'] = [0, 2, 0, 0, 2, 0, 0, 0, 1, 0, 0,
                            1, 0, 0, 0, 0, 1, 0, 0, 0, 0,
                            0, 0, 0, 0, 1, 1, 1, 0, 0, 0,
                            0, 0, 0, 0, 2, 2]
    fld_dct['rowNum'] = [1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12,
                         13, 14, 15, 16, 17, 18, 19, 20, 21, 22,
                         23, 24, 25, 26, 27, 28, 29, 30, 31, 32,
                         33, 34, 36, 37, 38, 39]
    fld_dct['allnos'] = [''] * 37
    fld_dct['average'] = [''] * 37

    #make table layer from results table
    arcpy.MakeTableView_management(outTbl,"rptbview")
    desc = arcpy.Describe("rptbview")
    fieldInfo = desc.fieldInfo
    cnt_rows = str(arcpy.GetCount_management(outTbl))

    for field in fld_dct['field']: #loop through fields
        idx = fld_dct['field'].index(field)
        #Check to see if field exists in results
        fldIndex = fieldInfo.findFieldByName(fld_dct['field'][idx])
        if fldIndex > 0: #exists
            if fld_dct['type'][idx] == 'Text': #narrow to yes/no
                #copy text field to list by field index
                fld_dct[idx] = field_to_lst(outTbl, field)
                #check if all 'NO'
                if fld_dct[idx].count("NO") == int(cnt_rows):
                    fld_dct['allnos'][idx] = 1
            else: #type = Double
                l = [x for x in field_to_lst(outTbl, field) if x is not None]
                if l != []: #if not all null
                    #get average values
                    fld_dct['average'][idx] = mean(l)
                    
    start = exec_time(start, "loading data for report")
    
    i = 1
    pg_cnt = 1
    siterows = arcpy.SearchCursor(outTbl,"") #may be slow #use "rptbview"?
    siterow = siterows.next()

    while siterow:

        oddeven = i % 2
        if oddeven == 1:
            column = 1
            siteText = "SiteLeftText"
            site_Name = "SiteLeftName"
        else:
            column = 2
            siteText = "SiteRightText"
            site_Name = "SiteRightName"

        siteText = arcpy.mapping.ListLayoutElements(mxd, "TEXT_ELEMENT", siteText)[0]
        siteText.text = "Site " + str(i)

        #text element processing
        siteName = arcpy.mapping.ListLayoutElements(mxd, "TEXT_ELEMENT", site_Name)[0]
        fldNameValue = "siterow." + siteNameFld
        if fieldInfo.findFieldByName(siteNameFld) > 0:
            if eval(fldNameValue) == ' ':
                siteName.text = "No name"
            else:
                siteName.text = eval(fldNameValue)
        else:
            siteName.text = "No name" 

        #loop through expected fields in fld_dct['field']
        for field in fld_dct['field']:
            idx = fld_dct['field'].index(field)
            #Check to see if field exists in results
            #if it doesn't color = black
            if fldExists(field, column, fld_dct['rowNum'][idx], fieldInfo, blackbox):
                fldVal = "siterow." + field
                if fld_dct['type'][idx] == 'Double': #is numeric   
                    proctext(eval(fldVal), "Num", fld_dct['numDigits'][idx],
                             fld_dct['ltorgt'][idx], fld_dct['average'][idx],
                             column, fld_dct['rowNum'][idx],
                             fld_dct['allnos'][idx], mxd)
                else: #is boolean
                    proctext(eval(fldVal), "Boolean", 0, "",
                             fld_dct['aveBool'][idx], column,
                             fld_dct['rowNum'][idx], fld_dct['allnos'][idx],
                             mxd)

        if oddeven == 0:
            exportReport(pdfDoc, pdf_path, pg_cnt, mxd)
            start = exec_time(start, "Page " + str(pg_cnt) + " generation")
            pg_cnt += 1
            
        i += 1
        siterow = siterows.next()

    # If you finish a layer with an odd number of records,
    # last record was not added to the pdf.
    if oddeven == 1:
        # Blank out right side
        siteText = arcpy.mapping.ListLayoutElements(mxd, "TEXT_ELEMENT",
                                                    "SiteRightText")[0]
        siteText.text = " "
        # Fill right side with gray empty boxes
        for i in range(39):
            # Not set up to process the Social Equity or Reliability scores
            newBox = graybox.clone("_clone")
            boxpos(newBox,2,i + 1)
        exportReport(pdfDoc, pdf_path, pg_cnt, mxd)

    del siterow
    del siterows

    arcpy.Delete_management("rptbview", "")

    pdfDoc.saveAndClose()

    mxd_result = os.path.splitext(pdf)[0] + ".mxd"
    if arcpy.Exists(mxd_result):
        arcpy.Delete_management(mxd_result)

    mxd.saveACopy(mxd_result) #save last page just in case

    del mxd
    del pdfDoc
    mxd_name = os.path.basename(mxd_result)
    message("Created PDF report: {} and {}".format(pdf, mxd_name))
##############################
######PRESENCE/ABSENCE########
def absTest_MODULE(PARAMS):
    """Presence Absence Test"""
    #start1 = time.clock() #start the clock
    
    outTbl, field = PARAMS[0], PARAMS[1]
    FC = PARAMS[2]
    buff_dist = PARAMS[3]
    
    path = os.path.dirname(outTbl) + os.sep
    ext = get_ext(outTbl)

    #set variables
    buff_temp = path + "feature_buffer" + ext
    FC = checkSpatialReference(outTbl, FC) #check spatial ref

    # Create buffers for each site by buff_dist.
    arcpy.Buffer_analysis(outTbl, buff_temp, buff_dist)

    #check if feature is present
    lst_present = buffer_contains(buff_temp, FC)
    booleanLst = []
    for item in lst_present:
        if item == 0:
            booleanLst.append("NO")
        else:
            booleanLst.append("YES")

    #move results to outTbl.field
    lst_to_AddField_lst(outTbl, [field], [booleanLst], ["Text"])
    arcpy.Delete_management(buff_temp)
    
##############################
#############MAIN#############
def main(params):
    """Main"""
    start = time.clock() #start the clock
    start1 = time.clock() #start the clock
    blank_warn = " some fields may be left blank for selected benefits."

    message("Loading Variables...")
    #params = [sites, addresses, popRast, flood, view, edu, rec, bird, socEq,
    #          rel, flood_zone, dams, edu_inst, bus_stp, trails, roads,
    #          OriWetlands, landUse, LULC_field, landVal, socVul, soc_Field, 
    #          socVal, conserve, conserve_Field, useVal, outTbl, pdf]
    ck=[]
    for i in range(3, 10):
        ck.append(params[i].value)
    flood, view, edu, rec, bird = ck[0], ck[1], ck[2], ck[3], ck[4]
    socEq, rel = ck[5], ck[6]
    
    sites = params[0].valueAsText #in_gdb  + "restoration_Sites"
    addresses = params[1].valueAsText #in_gdb + "e911_14_Addresses"
    popRast = params[2].valueAsText #None

    flood_zone = params[10].valueAsText #in_gdb + "FEMA_FloodZones_clp"
    subs = params[11].valueAsText #subs = in_gdb + "dams"
    edu_inst = params[12].valueAsText #in_gdb + "schools08"
    bus_Stp = params[13].valueAsText #in_gdb + "RIPTAstops0116"
    trails = params[14].valueAsText #in_gdb + "bikepath"
    roads = params[15].valueAsText #in_gdb + "e911Roads13q2"
    OriWetlands = params[16].valueAsText #in_gdb + "NWI14"

    landuse = params[17].valueAsText #in_gdb + "rilu0304"
    field = params[18].valueAsText #"LCLU"
    fieldLst = params[19].values #[u'161', u'162', u'410', u'430']
    if fieldLst != None:
        #coerce/map unicode list using field in table
        typ = tbl_fieldType(landuse, field)
        fieldLst = ListType_fromField(typ, fieldLst)

    sovi = params[20].valueAsText #in_gdb + "SoVI0610_RI"
    sovi_field = params[21].valueAsText #"SoVI0610_1"
    sovi_High = params[22].values #"High" #this is now a list...
    if sovi_High != None:
        #coerce/map unicode list using field in table
        typ = tbl_fieldType(sovi, sovi_field)
        sovi_High = ListType_fromField(typ, sovi_High)

    conserved = params[23].valueAsText #in_gdb + "LandUse2025"
    rel_field = params[24].valueAsText #"Map_Legend"
    cons_fLst = params[25].values
    #['Conservation/Limited', 'Major Parks & Open Space',
    # 'Narragansett Indian Lands', 'Reserve', 'Water Bodies']
    if cons_fLst != None:
        #convert unicode lists to field.type
        typ = tbl_fieldType(conserved, rel_field)
        cons_fLst = ListType_fromField(typ, cons_fLst)

        #all values from rel_field not in cons_fLst
        #['Non-urban Developed', 'Prime Farmland', 'Sewered Urban Developed',
        # 'Urban Development']
        uq_lst = unique_values(conserved, rel_field)
        threat_fieldLst = [x for x in uq_lst if x not in cons_fLst]
        
    #r"~\Tier1_pyt\Test_Results\IntermediatesFinal77.gdb\Results_full"
    outTbl = params[26].valueAsText
    pdf = params[27].valueAsText

    #DEFAULTS#
    #set buffers based on inputs
    if socEq == True:
        #buff_dist = params[22].valueAsText #"2.5 Miles"
        buff_dist = SocEqu_BuffDist(ck[0:5])
        message("Default buffer distance of {} used" +
                " for Social Equity".format(buff_dist))
    if rel == True:
        rel_buff_dist = "500 Feet"
        message("Default buffer distance of " + rel_buff_dist +
                " used for Benefit Reliability")

    #check for NHD+ files to prep correct datasets
    if not nhdPlus_check(None, None, None):
        message("Flood benefits will not be assessed")
        flood = None
        
    #package dir path (based on where this file is)
    script_dir = os.path.dirname(os.path.realpath(__file__)) + os.sep
    #check for report layout file
    if pdf != None:
        mxd_name = "report_layout.mxd"
        mxd = script_dir + mxd_name
        if arcpy.Exists(mxd):
            message("Using " + mxd + " report layout file")
        else:
            message("Default report layout file not available in expected" +
                    "location:\n{}".format(mxd))
            message("A PDF report will not be generated from results")
            pdf = None

    #Copy restoration wetlands in for results
    create_outTbl(sites, outTbl)

    start1 = exec_time(start1, "loading variables")       
    message("Checking input variables...")
    #check spatial references for inputs
    #all require pop except edu
    if True in [flood, view, rec, bird]:
        addresses, popRast = check_vars(outTbl, addresses, popRast)
    #trails
    if True in [view, bird, rec]:
        if trails is not None:
            trails = checkSpatialReference(outTbl, trails) #check spatial ref
            message("Trails input OK")
        else:
            message("Trails input not specified, " + blank_warn)
    # Roads
        if roads is not None:
            roads = checkSpatialReference(outTbl, roads) #check spatial ref
            message("Roads input OK")
        else:
            message("Roads input not specified, " + blank_warn)

    # Benefits requiring existing wetlands
    if True in [flood, view, edu, rec]:
        if OriWetlands is not None: #if the dataset is specified
            # Check spatial ref
            OriWetlands = checkSpatialReference(outTbl, OriWetlands)
            message("Existing wetlands OK")
        else:
            message("Existings wetlands input not specified, " + blank_warn)
    #benefits using landuse       
    if True in [view, rec]:
        if landuse is not None:
            landuse = checkSpatialReference(outTbl, landuse) #check spatial ref
            message("Landuse polygons OK")
        else:
            message("Landuse input not specified, " + blank_warn)
    #message/time:
    start1 = exec_time(start1, "verify inputs")
    message("Running selected benefit modules...")

    #run modules based on inputs
    if flood == True:
        Flood_PARAMS = [addresses, popRast, flood_zone, OriWetlands, subs,
                        None, None, None, outTbl]
        FR_MODULE(Flood_PARAMS)
        start1 = exec_time(start1, "Flood Risk Benefit assessment")
    else: #create and set all fields to none?
        message("Flood Risk Benefits not assessed")
        
    if view == True:
        View_PARAMS = [addresses, popRast, trails, roads, OriWetlands, landuse,
                       field, fieldLst, outTbl]
        View_MODULE(View_PARAMS)
        start1 = exec_time(start1, "Scenic View Benefit assessment")
    else: #create and set all fields to none?
        message("Scenic View Benefits not assessed")
                
    if edu == True:
        EDU_PARAMS = [edu_inst, OriWetlands, outTbl]
        Edu_MODULE(EDU_PARAMS)
        start1 = exec_time(start1, "Environmental Education Benefit assessment")
    else: #create and set all fields to none?
        message("Environmental Education Benefits not assessed")

    if rec == True:
        REC_PARAMS = [addresses, popRast, trails, bus_Stp, OriWetlands,
                      landuse, field, fieldLst, outTbl]
        Rec_MODULE(REC_PARAMS)
        start1 = exec_time(start1, "Recreation Benefit assessment")
    else: #create and set all fields to none?
        message("Recreation Benefits not assessed")
                
    if bird == True:
        Bird_PARAMS = [addresses, popRast, trails, roads, outTbl]
        Bird_MODULE(Bird_PARAMS)
        start1 = exec_time(start1, "Bird Watching Benefit assessment")
    else: #create and set all fields to none?
        message("Bird Watching Benefits not assessed")

    if socEq == True:
        soc_PARAMS = [sovi, sovi_field, sovi_High, buff_dist, outTbl]
        socEq_MODULE(soc_PARAMS)
        start1 = exec_time(start1, "Social Equity assessment")
    else: #create and set all fields to none?
        message("Social Equity of Benefits not assessed")
        
    if rel == True:
        Rel_PARAMS = [conserved, rel_field, cons_fLst, threat_fieldLst,
                      rel_buff_dist, outTbl]
        reliability_MODULE(Rel_PARAMS)
        start1 = exec_time(start1, "Reliability assessment")
    else: #create and set all fields to none?
        message("Reliability of Benefits not assessed")

    if pdf != None:
        #siteName defaults to OID unless there is a field named "siteName"
        lstFields = arcpy.ListFields(outTbl)
        siteName = arcpy.Describe(outTbl).OIDFieldName
        for fld in lstFields:
            if fld.name == "siteName":
                siteName = fld.name
        Report_PARAMS = [outTbl, siteName, mxd, pdf]
        Report_MODULE(Report_PARAMS)
        start1 = exec_time(start1, "Compiling assessment report")
    else:
        message("pdf Report not generated")
        
    start = exec_time(start, "complete Benefts assessment")
    
##############################
###########TOOLBOX############
class Toolbox(object):
    def __init__(self):
        self.label = "RBI Spatial Analysis Tools"
        self.alias = "RBI"
        # List of tool classes associated with this toolbox
        self.tools = [Tier_1_Indicator_Tool, FloodTool, Report, reliability,
                      socialVulnerability, presence_absence, FloodDataDownloader]

#############################      
class presence_absence(object):
    def __init__(self):
        self.label = "Part - Presence/Absence to Yes/No"
        self.description = "Use the presence or absence of some spatial" + \
                           " feature within a range of the site to" + \
                           " determine if that metric is YES or NO"
    def getParameterInfo(self):
        sites = setParam("Restoration Site Polygons (Required)", "in_poly", "", "", "")
        # Field in outTbl
        field = setParam("Field Name", "siteFld","Field", "", "")
        FC = setParam("Features", "feat", "", "", "")
        buff_dist = setParam("Buffer Distance", "bufferUnits", "GPLinearUnit", "", "")

        outTbl = setParam("Output", "outTable", "DEFeatureClass", "", "Output")

        field.parameterDependencies = [sites.name]
        
        params = [sites, field, FC, buff_dist, outTbl]
        return params
    
    def isLicensed(self):
        return True
    def updateParameters(self, params):
        return
    def updateMessages(self, params):
        return
    
    def execute(self, params, messages):
        start1 = time.clock() #start the clock

        sites = params[0].valueAsText
        field = params[1].valueAsText
        FC = params[2].valueAsText
        buff_dist = params[3].valueAsText
        outTbl = params[4].valueAsText

        create_outTbl(sites, outTbl)
        
        abs_test_PARAMS = [outTbl, field, FC, buff_dist]
        absTest_MODULE(abs_test_PARAMS)
        start1 = exec_time(start1, "Presence/Absence assessment")

################################        
class socialVulnerability (object):
    def __init__(self):
        self.label = "Part - Social Equity of Benefits"
        self.description = "Assess the social vulnerability of those" + \
                           " benefitting to identify social equity issues."
    def getParameterInfo(self):
        sites = setParam("Restoration Site Polygons (Required)", "in_poly", "", "", "")
        poly = setParam("Social Vulnerability", "sovi_poly", "", "", "")
        poly_field = setParam("Vulnerability Field", "SoVI_ScoreFld","Field", "", "")
        field_value = setParam("Vulnerable Field Values", "soc_field_val",
                               "GPString", "", "", True)
        buff_dist = setParam("Buffer Distance", "bufferUnits", "GPLinearUnit", "", "")

        outTbl = setParam("Output", "outTable", "DEFeatureClass", "", "Output")

        disableParamLst([poly_field, field_value]) #disable until source available
        poly_field.parameterDependencies = [poly.name]
        field_value.parameterDependencies = [poly_field.name]
        field_value.filter.type = 'ValueList'
        
        params = [sites, poly, poly_field, field_value, buff_dist, outTbl] 
        return params

    def isLicensed(self):
        return True
    def updateParameters(self, params):
        #social vulnerability inputs    
        if params[1].altered:
            params[2].enabled = True
        if params[2].altered: #socVul_field
            in_poly = params[1].valueAsText
            TypeField = params[2].valueAsText
            params[3].enabled = True
            params[3].filter.list = unique_values(in_poly, TypeField)
        return
    def updateMessages(self, params):
        return
    
    def execute(self, params, messages):
        start1 = time.clock() #start the clock
        
        sites = params[0].valueAsText
        outTbl = params[5].valueAsText

        create_outTbl(sites, outTbl)

        sovi = params[1].valueAsText
        sovi_field = params[2].valueAsText 
        sovi_High = params[3].values
        buff_dist = params[4].valueAsText

        if sovi_High != None: #coerce/map unicode list using field in table
            sovi_High = ListType_fromField(tbl_fieldType(sovi, sovi_field), sovi_High)        

        soc_PARAMS = [sovi, sovi_field, sovi_High, buff_dist, outTbl]
        socEq_MODULE(soc_PARAMS)
        start1 = exec_time(start1, "Social Equity assessment")
        
################################
###########Reliability##########
class reliability (object):
    def __init__(self):
        self.label = "Part - Benefit Reliability"
        self.description = "Assess the site's ability to produce services " + \
                           "and provide benefits into the future."
    def getParameterInfo(self):
        sites = setParam("Restoration Site Polygons (Required)", "in_poly", "", "", "")
        poly = setParam("Conservation Lands", "cons_poly", "", "", "")
        poly_field = setParam("Conservation Field", "Conservation_Field", "Field", "", "")
        in_lst = setParam("Conservation Types", "Conservation_Type", "GPString", "", "", True)
        buff_dist = setParam("Buffer Distance", "bufferUnits", "GPLinearUnit", "", "")
        outTbl = setParam("Output", "outTable", "DEFeatureClass", "", "Output")

        disableParamLst([poly_field, in_lst]) #disable until source available
        poly_field.parameterDependencies = [poly.name]
        in_lst.parameterDependencies = [poly_field.name]
        in_lst.filter.type = 'ValueList'

        params = [sites, poly, poly_field, in_lst, buff_dist, outTbl]
        return params

    def isLicensed(self):
        return True
    def updateParameters(self, params):
        if params[1].altered:
            params[2].enabled = True
        if params[2].altered: #socVul_field
            in_poly = params[1].valueAsText
            TypeField = params[2].valueAsText
            params[3].enabled = True
            params[3].filter.list = unique_values(in_poly, TypeField)
        return
    
    def updateMessages(self, params):
        return
    
    def execute(self, params, messages):
        start1 = time.clock() #start the clock
        sites = params[0].valueAsText
        outTbl = params[5].valueAsText

        create_outTbl(sites, outTbl)

        conserved = params[1].valueAsText
        field = params[2].valueAsText 
        cons_fieldLst = params[3].values
        buff_dist = params[4].valueAsText

        if cons_fieldLst != None:
            #convert unicode lists to field.type
            typ = tbl_fieldType(conserved, field)
            cons_fieldLst = ListType_fromField(typ, cons_fieldLst)
            #all values from rel_field not in cons_fieldLst
            uq_vals = unique_values(conserved, field)
            threat_fieldLst = [x for x in uq_vals if x not in cons_fieldLst]
        
        Rel_PARAMS = [conserved, field, cons_fieldLst, threat_fieldLst,
                      buff_dist, outTbl]
        try:
            reliability_MODULE(Rel_PARAMS)
            start1 = exec_time(start1, "Reliability assessment")
        except Exception:
            message("Error occured during Reliability assessment.")
            traceback.print_exc()
        
########Report Generator########
class Report (object):
    def __init__(self):
        self.label = "Part - Report Generation"
        self.description = "Tool to create formated summary pdf report of" + \
                           " indicator results"
    def getParameterInfo(self):
        outTbl = setParam("Results Table", "outTable", "DEFeatureClass", "", "")
        siteName = setParam("Site Names Field", "siteNameField", "Field", "", "")
        siteName.enabled = False
        mxd = setParam("Mapfile with report layout", "mxd", "DEMapDocument", "", "")
        pdf = setParam("pdf Report", "outReport", "DEFile", "", "Output")

        siteName.parameterDependencies = [outTbl.name]
        
        params = [outTbl, siteName, mxd, pdf]
        return params

    def isLicensed(self):
        return True
    def updateParameters(self, params):
        if params[0].value != None:
            params[1].enabled = True
        else:
            params[1].enabled = False
        return
    def updateMessages(self, params):
        return
    
    def execute(self, params, messages):
        start1 = time.clock() #start the clock

        outTbl = params[0].valueAsText
        siteName = params[1].valueAsText
        mxd = params[2].valueAsText 
        pdf = params[3].valueAsText
        
        Report_PARAMS = [outTbl, siteName, mxd, pdf]
        Report_MODULE(Report_PARAMS)
        start1 = exec_time(start1, "Compile assessment report")
        
###########FLOOD_TOOL###########
class FloodTool (object):
    def __init__(self):
        self.label = "Part - Flood Risk Reduction "
        self.description = "This tool assesses Flood Risk Reduction Benefits"

    def getParameterInfo(self):
    #Define IN/OUT parameters
        #sites = in_gdb  + "restoration_Sites"
        sites = setParam("Restoration Site Polygons (Required)", "in_poly", "", "", "")
        #addresses = in_gdb + "e911_14_Addresses" #beneficiaries points
        addresses = setParam("Address Points", "in_pnts", "", "Optional", "")
        #popRast = None #beneficiaries raster
        popRast = setParam("Population Raster", "popRast", "DERasterDataset", "Optional", "")

        #flood_zone = in_gdb + "FEMA_FloodZones_clp"
        flood_zone = setParam("Flood Zone Polygons", "flood_zone", "", "", "")
        #subs = in_gdb + "dams"
        dams = setParam("Dams/Levee", "flood_sub", "", "", "")
        #pre-existing wetlands #OriWetlands = in_gdb + "NWI14"
        OriWetlands = setParam("Wetland Polygons", "in_wet", "", "", "")
        #catchment = "~NHDPlusV21_National_Seamless.gdb\NHDPlusCatchment\Catchment"
        catchment = setParam("NHD+ Catchments", "NHD_catchment" , "", "Optional", "")
        #FloodField = "FEATUREID"
        FloodField = setParam("NHD Join Field", "inputField", "Field", "Optional", "")
        #relationship table = PlusFlow.dbf
        relateTable = setParam("Relationship Table", "Flow", "DEDbaseTable", "Optional","")
        #outTbl = r"~\Test_Results\IntermediatesFinal77.gdb\Results_full"
        outTbl = setParam("Output", "outTable", "DEFeatureClass", "", "Output")

        params = [sites, addresses, popRast, flood_zone, OriWetlands, dams,
                  catchment, FloodField, relateTable, outTbl]
        return params

    def isLicensed(self):
        return True
    def updateParameters(self, params):
        #Take only addresses or raster
        if params[1].value != None:
            params[2].enabled = False
        else:
            params[2].enabled = True
        if params[2].value != None:
            params[1].enabled = False
        else:
            params[1].enabled = True
        return
    
    def updateMessages(self, params):
        return
    
    def execute(self, params, messages):
        #[sites, addresses, popRast, flood_zone, OriWetlands, dams, catchment,
        # FloodField, outTbl]
        start1 = time.clock() #start the clock
        sites = params[0].valueAsText
        outTbl = params[9].valueAsText
        
        addresses = params[1].valueAsText #in_gdb + "e911_14_Addresses"
        popRast = params[2].valueAsText #None
        
        flood_zone = params[3].valueAsText
        OriWetlands = params[4].valueAsText #in_gdb + "NWI14"
        subs = params[5].valueAsText
        catchment = params[6].valueAsText
        inputField = params[7].valueAsText
        rel_Tbl = params[8].valueAsText

        create_outTbl(sites, outTbl)
        # Check spatial ref
        addresses, popRast = check_vars(outTbl, addresses, popRast)

        if OriWetlands is not None: #if the dataset is specified
            # Check spatial ref
            OriWetlands = checkSpatialReference(outTbl, OriWetlands)
            message("Existing wetlands OK")
        else:
            message("Existing wetlands input not specified, some fields " +
                    "may be left blank for selected benefits.")

        Flood_PARAMS = [addresses, popRast, flood_zone, OriWetlands, subs,
                        catchment, inputField, rel_Tbl, outTbl]
        FR_MODULE(Flood_PARAMS)
        start1 = exec_time(start1, "Flood Risk benefit assessment")
################################
class FloodDataDownloader(object):
    def __init__(self):
        self.label = "Part - Flood Data Download"
        self.description = "Download NHD Plus data. Requires web access."
    def getParameterInfo(self):
        sites = setParam("Restoration Site Polygons (Required)", "in_poly", "", "", "")
        # NHDPlus boundaries
        NHD_VUB = setParam("NHD Plus Vector Processing Unit", "VUB", "", "Optional", "")
        # Location to save catchments
        local = setParam("Download Folder", "outTable", "DEFeatureClass", "Optional", "Output")

        params = [sites, NHD_VUB, local]
        return params
    
    def isLicensed(self):
        return True
    def updateParameters(self, params):
        return
    def updateMessages(self, params):
        return

    def execute(self, params, messages):
        start = time.clock() #start the clock

        sites = params[0].valueAsText
        NHD_VUB = params[1].valueAsText
        local = params[2].valueAsText

        NHD_PARAMS = [sites, NHD_VUB, local]
        NHD_get_MODULE(NHD_PARAMS)

        start = exec_time(start, "Downloading NHD Plus Stream Data")

        
################################        
#########INDICATOR_TOOL#########       
class Tier_1_Indicator_Tool (object):
    def __init__(self):
        self.label = "Full Indicator Assessment" 
        self.description = "This tool performs the Tier 1 Indicators" + \
                           " assessment on a desired set of wetlands"  + \
                           " or wetlands restoration sites."

    def getParameterInfo(self):
    #Define IN/OUT parameters
        opt = "Optional"
        GP_s = "GPString"
        GP_b = "GPBoolean"
        fld = "Field"
        #sites = in_gdb  + "restoration_Sites"
        sites = setParam("Restoration Site Polygons (Required)", "in_poly", "", "", "")
        #addresses = in_gdb + "e911_14_Addresses" #beneficiaries points
        addresses = setParam("Address Points", "in_pnts", "", opt, "")
        #popRast = None
        #beneficiaries raster
        popRast = setParam("Population Raster", "popRast", "DERasterDataset", opt, "")
        # Check boxes for services the user wants to assess
        #flood, view, edu, rec, bird, socEq, rel = True
        serviceLst=["Reduced Flood Risk", "Scenic Views",
                    "Environmental Education", "Recreation", 
                    "Bird Watching", "Social Equity", "Reliability"]
        flood = setParam(serviceLst[0], "flood", GP_b, opt, "")
        view = setParam(serviceLst[1], "view", GP_b, opt, "")
        edu = setParam(serviceLst[2], "edu", GP_b, opt, "")
        rec = setParam(serviceLst[3], "rec", GP_b, opt, "")
        bird = setParam(serviceLst[4], "bird", GP_b, opt, "")
        socEq = setParam(serviceLst[5], "socEq", GP_b, opt, "")
        rel = setParam(serviceLst[6], "rel", GP_b, opt, "")

        #flood_zone = in_gdb + "FEMA_FloodZones_clp"
        flood_zone = setParam("Flood Zone Polygons", "flood_zone", "", opt, "")
        #subs = in_gdb + "dams"
        dams = setParam("Dams/Levees", "flood_sub", "", opt, "")
        #edu_inst = in_gdb + "schools08"
        edu_inst = setParam("Educational Institution Points", "edu_inst", "", opt, "")
        #bus_Stp = in_gdb + "RIPTAstops0116"
        #could it accomodate lines too?
        bus_stp = setParam("Bus Stop Points", "bus_stp", "", opt, "")
        #trails = in_gdb + "bikepath"
        trails = setParam("Trails (hiking, biking, etc.)", "trails", "", opt, "")
        #roads = in_gdb + "e911Roads13q2"
        roads = setParam("Roads (streets, highways, etc.)", "roads", "", opt, "")
        #pre-existing wetlands #OriWetlands = in_gdb + "NWI14"
        OriWetlands = setParam("Wetland Polygons", "in_wet", "", opt, "")

        #landuse = in_gdb + "rilu0304"
        landUse = setParam("Landuse/Greenspace Polygons", "land_use", "", opt, "")
        #field = "LCLU"
        LULC_field = setParam("Greenspace Field", "LULCFld", fld, opt, "")
        # List of fields from table [430, 410, 162, 161].
        landVal = setParam("Greenspace Field Values", "grn_field_val", GP_s, opt, "", True)

        #sovi = in_gdb + "SoVI0610_RI"
        socVul = setParam("Social Vulnerability", "sovi_poly", "", opt, "")
        # User must select 1 field to base calculation on.
        #sovi_field = "SoVI0610_1"
        soc_Field = setParam("Vulnerability Field", "SoVI_ScoreFld", fld, opt, "")
        #sovi_High = "High"
        socVal = setParam("Vulnerable Field Values", "soc_field_val", GP_s, opt, "", True)

        #conserved = in_gdb + "LandUse2025"
        conserve = setParam("Conservation Lands", "cons_poly", "", opt, "")
        #rel_field = "Map_Legend"
        conserve_Field = setParam("Conservation Field", "Conservation_Field", fld, opt, "")
        #user must select 1 field to base calculation on
        #cons_fieldLst = ['Conservation/Limited', 'Major Parks & Open Space',
        #                 'Narragansett Indian Lands', 'Reserve',
        #                 'Water Bodies']
        useVal = setParam("Conservation Types", "Conservation_Type", GP_s, opt, "", True)
                
        #outputs
        #outTbl = r"~\Test_Results\IntermediatesFinal77.gdb\Results_full"
        outTbl = setParam("Output", "outTable", "DEFeatureClass", "", "Output")
        #outTbl = setParam("Output", "outTable", "DEWorkspace", "", "Output")

        pdf = setParam("PDF Report", "outReport", "DEFile", opt, "Output")

        #set inputs to be disabled until benefits are selected
        disableParamLst([flood_zone, dams, edu_inst, bus_stp, trails, roads,
                         OriWetlands, landUse, LULC_field, landVal, socVul,
                         soc_Field, socVal, conserve, conserve_Field, useVal])

	#Set FieldsLists to be filtered by the list from the feature dataset field
        LULC_field.parameterDependencies = [landUse.name]
        landVal.parameterDependencies = [LULC_field.name]
        landVal.filter.type = 'ValueList'
        
        soc_Field.parameterDependencies = [socVul.name]
        socVal.parameterDependencies = [soc_Field.name]
        socVal.filter.type = 'ValueList'
        
        conserve_Field.parameterDependencies = [conserve.name]
        useVal.parameterDependencies = [conserve_Field.name]
        useVal.filter.type = 'ValueList'

        params = [sites, addresses, popRast, flood, view, edu, rec, bird,
                  socEq, rel, flood_zone, dams, edu_inst, bus_stp, trails,
                  roads, OriWetlands, landUse, LULC_field, landVal, socVul,
                  soc_Field, socVal, conserve, conserve_Field, useVal, outTbl,
                  pdf]

        return params

    def isLicensed(self):
        return True
    def updateParameters(self, params):
        # Modify the values and properties of parameters before internal
        #validation is performed.
        #Called whenever a parameter is changed.
        p = params
        # Only take points or raster
        if p[1].value != None:
            p[2].enabled = False
        else:
            p[2].enabled = True
        if p[2].value != None:
            p[1].enabled = False
        else:
            p[1].enabled = True
        # Flood only inputs (flood zone & dams)
        if p[3].value == True: #option button
            p[10].enabled = True #zone
            p[11].enabled = True #dams
        else:
            p[10].enabled = False
            p[11].enabled = False
        #edu only inputs (edu_inst)
        if p[5].value == True:
            p[12].enabled = True
        else:
            p[12].enabled = False
        #rec only inputs (bus_stp)
        if p[6].value == True:
            p[13].enabled = True
        else:
            p[13].enabled = False
        #trails required benefits (view, rec, bird)
        if True in set([p[4].value, p[6].value, p[7].value]):
            p[14].enabled = True
        else:
            p[14].enabled = False 
        #roads required benefits (view, bird)
        if True in [params[4].value, params[7].value]:
            p[15].enabled = True
        else:
            p[15].enabled = False
        # Wetlands required benefits (flood, view, edu, rec).
        lst = [p[3].value, p[4].value, p[5].value, p[6].value]
        if True in set(lst):
            p[16].enabled = True
        else:
            p[16].enabled = False 
        # landuse required benefits (view & rec).
        if True in [p[4].value, p[6].value]:
            p[17].enabled = True
        else:
            p[17].enabled = False
        if p[17].altered:
            p[18].enabled = True
        if p[18].altered:
            in_poly = p[17].valueAsText
            TypeField = p[18].valueAsText
            p[19].enabled = True
            p[19].filter.list = unique_values(in_poly, TypeField)
        #social vulnerability inputs    
        if p[8].value == True:
            p[20].enabled = True #SocVul
        else:
            p[20].enabled = False
        if p[20].altered:
            p[21].enabled = True
        if p[21].altered: #socVul_field
            in_poly = p[20].valueAsText
            TypeField = p[21].valueAsText
            p[22].enabled = True
            p[22].filter.list = unique_values(in_poly, TypeField)
        #reliability inputs
        if p[9].value == True:
            p[23].enabled = True #Conservation
        else:
            p[23].enabled = False
        if p[23].altered:
            p[24].enabled = True #Conserve_Field
        if p[24].altered: 
            in_poly = p[23].valueAsText
            TypeField = p[24].valueAsText
            p[25].enabled = True
            p[25].filter.list = unique_values(in_poly, TypeField)
        return

    def updateMessages(self, params):
        """This method is called after internal validation."""
        #params[].setErrorMessage('') #use to validate inputs
        return
    
    def execute(self, params, messages):
        main(params)
