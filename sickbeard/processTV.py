# Author: Nic Wolfe <nic@wolfeden.ca>
# URL: http://code.google.com/p/sickbeard/
#
# This file is part of Sick Beard.
#
# Sick Beard is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Sick Beard is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Sick Beard.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import with_statement

import os
import shutil

import sickbeard
from sickbeard import postProcessor
from sickbeard import db, helpers, exceptions

from sickbeard import encodingKludge as ek
from sickbeard.exceptions import ex

from sickbeard import logger

from sickbeard import failedProcessor

from sickbeard.name_parser.parser import NameParser, InvalidNameException


def logHelper (logMessage, logLevel=logger.MESSAGE):
    logger.log(logMessage, logLevel)
    return logMessage + u"\n"

def processDir (dirName, nzbName=None, recurse=False, failed=False):
    """
    Scans through the files in dirName and processes whatever media files it finds

    dirName: The folder name to look in
    nzbName: The NZB name which resulted in this folder being downloaded
    recurse: Boolean for whether we should descend into subfolders or not
    failed: Boolean for whether or not the download failed
    """

    returnStr = ''

    returnStr += logHelper(u"Processing folder "+dirName, logger.DEBUG)

    returnStr += logHelper(u"TV_DOWNLOAD_DIR: " + sickbeard.TV_DOWNLOAD_DIR, logger.DEBUG)

    # if they passed us a real dir then assume it's the one we want
    if ek.ek(os.path.isdir, dirName):
        dirName = ek.ek(os.path.realpath, dirName)

    # if the client and Sickbeard are not on the same machine translate the Dir in a network dir
    elif sickbeard.TV_DOWNLOAD_DIR and ek.ek(os.path.isdir, sickbeard.TV_DOWNLOAD_DIR) \
            and ek.ek(os.path.normpath, dirName) != ek.ek(os.path.normpath, sickbeard.TV_DOWNLOAD_DIR):
        dirName = ek.ek(os.path.join, sickbeard.TV_DOWNLOAD_DIR, ek.ek(os.path.abspath, dirName).split(os.path.sep)[-1])
        returnStr += logHelper(u"Trying to use folder "+dirName, logger.DEBUG)

    # if we didn't find a real dir then quit
    if not ek.ek(os.path.isdir, dirName):
        returnStr += logHelper(u"Unable to figure out what folder to process. If your downloader and Sick Beard aren't on the same PC make sure you fill out your TV download dir in the config.", logger.DEBUG)
        return returnStr

    if failed:
        try:
            processor = failedProcessor.FailedProcessor(dirName, nzbName)
            process_result = processor.process()
            process_fail_message = ""
        except exceptions.FailedProcessingFailed, e:
            process_result = False
            process_fail_message = ex(e)

        returnStr += processor.log 

        if sickbeard.DELETE_FAILED and process_result:
            returnStr += logHelper(u"Deleting folder of failed download " + dirName, logger.DEBUG)
            try:
                shutil.rmtree(dirName)
            except (OSError, IOError), e:
                returnStr += logHelper(u"Warning: Unable to remove the failed folder " + dirName + ": " + ex(e), logger.WARNING)

        if process_result:
            returnStr += logHelper(u"Processing succeeded: (" + str(nzbName) + ", " + dirName + ")")
        else:
            returnStr += logHelper(u"Processing failed: (" + str(nzbName) + ", " + dirName + "): " + process_fail_message, logger.WARNING)
        return returnStr

    if dirName == sickbeard.TV_DOWNLOAD_DIR and not nzbName: #Scheduled Post Processing Active
        #Get at first all the subdir in the dirName
        for path, dirs, files in ek.ek(os.walk, dirName):
            break
    else:
        path, dirs = ek.ek(os.path.split, dirName) #Script Post Processing
        if not nzbName is None and not nzbName.endswith('.nzb') and os.path.isfile(os.path.join(dirName, nzbName)): #For single torrent file without Dir
            files = [os.path.join(dirName, nzbName)]
            dirs = []
        else:
            files = ek.ek(os.listdir, dirName)
            dirs = [dirs]

    process_result = False
    videoFiles = filter(helpers.isMediaFile, files)

    # Check for orphaned helper files for keeping track of processed state
    if sickbeard.KEEP_PROCESSED_DIR:
        removeOrphanedProcessedHelperFiles(dirName, files)

    # If nzbName is set and there's more than one videofile in the folder, files will be lost (overwritten).
    if nzbName != None and len(videoFiles) >= 2:
        nzbName = None

    returnStr += logHelper(u"PostProcessing Path: " + path, logger.DEBUG)
    returnStr += logHelper(u"PostProcessing Dirs: " + str(dirs), logger.DEBUG)
    returnStr += logHelper(u"PostProcessing Files: " + str(files), logger.DEBUG)
    returnStr += logHelper(u"PostProcessing VideoFiles: " + str(videoFiles), logger.DEBUG)

    #Process Video File in the current Path
    for cur_video_file in videoFiles:

        cur_video_file_path = ek.ek(os.path.join, dirName, cur_video_file)

        # prevent infinite auto process loop when KEEP_PROCESSED_DIR = true, by marking videos as processed
        if sickbeard.KEEP_PROCESSED_DIR and hasProcessedHelperFile(cur_video_file_path):
            logHelper(u"Processing skipped for " + cur_video_file_path + ": .processed file detected.")
            continue

        try:
            processor = postProcessor.PostProcessor(cur_video_file_path, nzbName)
            process_result = processor.process()
            process_fail_message = ""
        except exceptions.PostProcessingFailed, e:
            process_result = False
            process_fail_message = ex(e)

        returnStr += processor.log

        if process_result:
            returnStr += logHelper(u"Processing succeeded for "+cur_video_file_path)
        else:
            returnStr += logHelper(u"Processing failed for "+cur_video_file_path+": "+process_fail_message, logger.WARNING)

    #Process Video File in all TV Subdir
    for dir in [x for x in dirs if validateDir(path, x, returnStr)]:
        
        for processPath, processDir, fileList in ek.ek(os.walk, ek.ek(os.path.join, path, dir), topdown=False):

            #TODO ADD some other checking

            videoFiles = filter(helpers.isMediaFile, fileList)
            notwantedFiles = [x for x in fileList if x not in videoFiles]

#            # Do not process video files in root directory a second time (copies and symbolic/physical links may remain).
#            if processPath == dirName:
#                videoFiles = []

            # Do not process video files in root directory a second time (copies and symbolic/physical links may remain).
            if processPath == dirName:
                videoFiles = []

            # If nzbName is set and there's more than one videofile in the folder, files will be lost (overwritten).
            if nzbName != None and len(videoFiles) >= 2:
                nzbName = None

            for cur_video_file in videoFiles:

                cur_video_file_path = ek.ek(os.path.join, processPath, cur_video_file)

                # prevent infinite auto process loop when KEEP_PROCESSED_DIR = true, by marking videos as processed
                if sickbeard.KEEP_PROCESSED_DIR and hasProcessedHelperFile(cur_video_file_path):
                    logHelper(u"Processing skipped for " + cur_video_file_path + ": .processed file detected.")
                    continue

                try:
                    processor = postProcessor.PostProcessor(cur_video_file_path, nzbName)
                    process_result = processor.process()
                    process_fail_message = ""
                except exceptions.PostProcessingFailed, e:
                    process_result = False
                    process_fail_message = ex(e)

                returnStr += processor.log

                if process_result:
                    returnStr += logHelper(u"Processing succeeded for "+cur_video_file_path)
                else:
                    returnStr += logHelper(u"Processing failed for "+cur_video_file_path+": "+process_fail_message, logger.WARNING)

                #If something fail abort the processing on dir
                if not process_result:
                    break

            # Check for orphaned helper files for keeping track of processed state
            if sickbeard.KEEP_PROCESSED_DIR:
                removeOrphanedProcessedHelperFiles(processDir, fileList)

            #Delete all file not needed
            for cur_file in notwantedFiles:
                if sickbeard.PROCESS_METHOD != "move" or not process_result:
                    break

                cur_file_path = ek.ek(os.path.join, processPath, cur_file)

                try:
                    processor = postProcessor.PostProcessor(cur_file_path, nzbName)
                    processor._delete(cur_file_path)
                    returnStr += logHelper(u"Deleting succeeded for " + cur_file_path, logger.DEBUG)
                except exceptions.PostProcessingFailed, e:
                    process_fail_message = ex(e)

                returnStr += processor.log

            if sickbeard.PROCESS_METHOD == "move" and \
            ek.ek(os.path.normpath, processPath) != ek.ek(os.path.normpath, sickbeard.TV_DOWNLOAD_DIR):

                if not ek.ek(os.listdir, processPath) == []:
                    returnStr += logHelper(u"Skipping Deleting folder " + processPath + ' because some files was not deleted/processed', logger.DEBUG)
                    continue

                returnStr += logHelper(u"Deleting folder " + processPath, logger.DEBUG)
                returnStr += logHelper(u"Processing succeeded for "+cur_video_file_path)

                try:
                    shutil.rmtree(processPath)
                except (OSError, IOError), e:
                    returnStr += logHelper(u"Warning: unable to remove the folder " + dirName + ": " + ex(e), logger.WARNING)

    return returnStr

def validateDir(path, dirName, returnStr):

    returnStr += logHelper(u"Processing folder "+dirName, logger.DEBUG)

    # TODO: check if it's failed and deal with it if it is
    if ek.ek(os.path.basename, dirName).startswith('_FAILED_'):
        returnStr += logHelper(u"The directory name indicates it failed to extract, cancelling", logger.DEBUG)
        return False
    elif ek.ek(os.path.basename, dirName).startswith('_UNDERSIZED_'):
        returnStr += logHelper(u"The directory name indicates that it was previously rejected for being undersized, cancelling", logger.DEBUG)
        return False
    elif ek.ek(os.path.basename, dirName).startswith('_UNPACK_'):
        returnStr += logHelper(u"The directory name indicates that this release is in the process of being unpacked, skipping", logger.DEBUG)
        return False

    # make sure the dir isn't inside a show dir
    myDB = db.DBConnection()
    sqlResults = myDB.select("SELECT * FROM tv_shows")
    for sqlShow in sqlResults:
        if dirName.lower().startswith(ek.ek(os.path.realpath, sqlShow["location"]).lower()+os.sep) or dirName.lower() == ek.ek(os.path.realpath, sqlShow["location"]).lower():
            returnStr += logHelper(u"You're trying to post process an episode that's already been moved to its show dir", logger.ERROR)
            return False

    # Get the videofile list for the next checks
    files = ek.ek(os.listdir, os.path.join(path, dirName))
    videoFiles = filter(helpers.isMediaFile, files)

    # Avoid processing the same dir again if we use KEEP_PROCESSING_DIR    
    if sickbeard.KEEP_PROCESSED_DIR:
        numPostProcFiles = myDB.select("SELECT COUNT(release_name) as numfiles FROM tv_episodes WHERE release_name = ?", [dirName])
        if int(numPostProcFiles[0][0]) == len(videoFiles):
            returnStr += logHelper(u"You're trying to post process a dir that's already been processed, skipping", logger.DEBUG)
            return False
    return True

# Check and remove, .processed helper files that have no accompanying files anymore
def removeOrphanedProcessedHelperFiles(baseDir, fileList):
    processedFiles = filter(isProcessedHelperFile, fileList)

    for processedFile in processedFiles:
        # get filename without extension
        baseName = processedFile.rpartition(".")[0]

        # search the file list for all the files starting with baseName
        matches = [file for file in fileList if file.startswith(baseName)]

        # if only one matches, this is the current .processed file and it is orphaned; so it can be deleted
        if len(matches) == 1:
            os.remove(ek.ek(os.path.join, baseDir, processedFile))

# Check if a file is a .processed helper file
def isProcessedHelperFile(file):
    sepFile = file.rpartition(".")

    if sepFile[0] == "":
        return False
    else:
        return sepFile[2] == "processed"

# Check if a video file has a .processed helper file (so we can skip the video)
def hasProcessedHelperFile(file):
    # check if file has already been processed - an empty helper file will exist
    helper_file = helpers.replaceExtension(file, "processed")
    if ek.ek(os.path.isfile, helper_file):
        return True
    return False
