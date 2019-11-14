# -*- coding: utf-8 -*-
"""
***************************************************************************
    uav_footprint.py
    ---------------------
    Date                 : August 2019QgsPoint
    Copyright            : (C) 2019 by Luigi Pirelli
    Email                : luipir at gmail dot com
***************************************************************************
*                                                                         *
*   This program is free software; you can redistribute it and/or modify  *
*   it under the terms of the GNU General Public License as published by  *
*   the Free Software Foundation; either version 2 of the License, or     *
*   (at your option) any later version.                                   *
*                                                                         *
***************************************************************************
"""

__author__ = 'Luigi Pirelli'
__date__ = 'August 2019'
__copyright__ = '(C) 2019, Luigi Pirelli'

import shutil
import os
import sys
import time
import math
import traceback
from collections import OrderedDict
from xml.etree import cElementTree as ElementTree
from osgeo import gdal

from qgis.PyQt.QtCore import (QCoreApplication,
                              QVariant)
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingException,
                       QgsProcessingParameterDefinition,
                       QgsProcessingParameterMultipleLayers,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterCrs,
                       QgsCoordinateTransform,
                       QgsProject,
                       QgsPointXY,
                       QgsPoint,
                       QgsGeometry,
                       QgsFeature,
                       QgsWkbTypes,
                       QgsFeatureSink,
                       QgsField,
                       QgsFields,
                       QgsWkbTypes)
import processing

###############################################
# XML to dict parsing code get from:
# https://stackoverflow.com/questions/2148119/how-to-convert-an-xml-string-to-a-dictionary
class XmlListConfig(list):
    def __init__(self, aList):
        for element in aList:
            if element:
                # treat like dict
                if len(element) == 1 or element[0].tag != element[1].tag:
                    self.append(XmlDictConfig(element))
                # treat like list
                elif element[0].tag == element[1].tag:
                    self.append(XmlListConfig(element))
            elif element.text:
                text = element.text.strip()
                if text:
                    self.append(text)


class XmlDictConfig(dict):
    '''
    Example usage:
    >>> tree = ElementTree.parse('your_file.xml')
    >>> root = tree.getroot()
    >>> xmldict = XmlDictConfig(root)
    Or, if you want to use an XML string:
    >>> root = ElementTree.XML(xml_string)
    >>> xmldict = XmlDictConfig(root)
    And then use xmldict for what it is... a dict.
    '''
    def __init__(self, parent_element):
        if parent_element.items():
            self.update(dict(parent_element.items()))
        for element in parent_element:
            if element:
                # treat like dict - we assume that if the first two tags
                # in a series are different, then they are all different.
                if len(element) == 1 or element[0].tag != element[1].tag:
                    aDict = XmlDictConfig(element)
                # treat like list - we assume that if the first two tags
                # in a series are the same, then the rest are the same.
                else:
                    # here, we put the list in dictionary; the key is the
                    # tag name the list elements all share in common, and
                    # the value is the list itself 
                    aDict = {element[0].tag: XmlListConfig(element)}
                # if the tag has attributes, add those to the dict
                if element.items():
                    aDict.update(dict(element.items()))
                self.update({element.tag: aDict})
            # this assumes that if you've got an attribute in a tag,
            # you won't be having any text. This may or may not be a 
            # good idea -- time will tell. It works for the way we are
            # currently doing XML configuration files...
            elif element.items():
                self.update({element.tag: dict(element.items())})
            # finally, if there are no child tags and no attributes, extract
            # the text
            else:
                self.update({element.tag: element.text})

###############################################

def _convert_to_degress(value):
    """
    Helper function to convert the GPS coordinates stored in the EXIF to degress in float format
    :param value:
    :type value: str (e.g. '(43) (16) (20.3444)')
    :rtype: float
    """
    values = value.translate(str.maketrans({'(':None, ')':None})).split()
    d = float(values[0])
    m = float(values[1])
    s = float(values[2])

    return d + (m / 60.0) + (s / 3600.0)

def tr(text):
    return QCoreApplication.translate(text)

class BatchUAVImageFootprints(QgsProcessingAlgorithm):

    INPUT_LAYERS = 'INPUT_LAYERS'
    CAMERA_MODEL = 'CAMERA_MODEL'
    OUTPUT_FOOTPRINTS = 'OUTPUT_FOOTPRINTS'
    OUTPUT_NADIRS = 'OUTPUT_NADIRS'

    OUTPUT_FOOTPRINTS_FILENAME = 'footprints.gpkg'
    OUTPUT_NADIRS_FILENAME = 'nadirs.gpkg'

    SOURCE_CRS = 'SOURCE_CRS'
    DESTINATION_CRS = 'DESTINATION_CRS'
    HORIZONTAL_FOV = 'HORIZONTAL_FOV'
    VERTICAL_FOV = 'VERTICAL_FOV'
    NADIR_TO_BOTTOM_OFFSET = 'NADIR_TO_BOTTOM_OFFSET'
    NADIR_TO_UPPPER_OFFSET = 'NADIR_TO_UPPPER_OFFSET'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return BatchUAVImageFootprints()

    def group(self):
        return self.tr('UAV tools')

    def groupId(self):
        return 'Batch images footprints'

    def __init__(self):
        super().__init__()

        self.CAMERA_DATA = OrderedDict([
            (self.tr('Phantom 4 Pro - FC6310'), {
                'horizontal_FOV': 67.07,
                'vertical_FOV': 52.86,
                'nadir_to_bottom_offset': 0,
                'nadir_to_upper_offset': 0
            }),
            (self.tr('DJI - X3'), {
                'horizontal_FOV': 82.3,
                'vertical_FOV': 66.46,
                'nadir_to_bottom_offset': 0,
                'nadir_to_upper_offset': 0
            }),
            (self.tr('MicaSense - Altum'), {
                'horizontal_FOV': 64,
                'vertical_FOV': 84,
                'nadir_to_bottom_offset': 0,
                'nadir_to_upper_offset': 0
            }),
            (self.tr('Advanced'), {
                'horizontal_FOV': 64,
                'vertical_FOV': 84,
                'nadir_to_bottom_offset': 0,
                'nadir_to_upper_offset': 0
            })
        ])

    def name(self):
        return 'batchuavimagesfootprints'

    def displayName(self):
        return self.tr('Batch UAV images footprints')

    def shortHelpString(self):
        return self.tr('''The algoritm generates the nadir drone point and the obligual camera footprint polygon (not dem proyected)
                       basing on image metadata (EXIF and XMP).\n
                       It uses Wedge buffer processing algoritm to create the polygon => Generate error if pitch angle is greater
                       than (-45 degree -verticalFOV/2 ) e.g. if buffer distance is negative.\n
                       Advanced parameters are useful to adjust the footprint to the camera view. The camera model does not consider
                       camera distorsion and calibration model\n
                       The gemetric algoritm to calculate footprint is based simple trigonometry and ispired by StackOverflow <a href="https://photo.stackexchange.com/questions/56596/how-do-i-calculate-the-ground-footprint-of-an-aerial-camera">post</a>

                       <b>Advanced parameters</b>
                       <b>Calc vertical FOV using image ratio</b>: If Checked the vertical FOV (Tall camera angle) is calculated. If Unckeked get the value from "Tall camera angle" field
                       <b>Tall camera angle</b>: Use this value if "Calc Vertical FOV using image ratio" is uncheked
                       <b>Empiric multiplier to fix tall FOV basing on image ratio</b>: A multiplier applied to calculated vertical FOV useful to adapt angle to the real view. Many times vertical FOV is a hard to discover value not registerd in the metadata.
                       <b>Offset to add to bottom distance result</b>: value added to nadir point dinstance
                       <b>Offset to add to upper distance result</b>:value added to nadir point dinstance
                       ''')

    def initAlgorithm(self, config=None):

        self.addParameter(
            QgsProcessingParameterMultipleLayers(self.INPUT_LAYERS,
                                                self.tr('Input layers'),
                                                QgsProcessing.TypeRaster)
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink (
                self.OUTPUT_FOOTPRINTS,
                self.tr('Images footprint'),
                QgsProcessing.TypeVectorPolygon)
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink (
                self.OUTPUT_NADIRS,
                self.tr('Images nadir'),
                QgsProcessing.TypeVectorPoint)
        )

        self.addParameter(
            QgsProcessingParameterEnum (
                self.CAMERA_MODEL,
                self.tr('Camera model defining FOV values'),
                options=list(self.CAMERA_DATA.keys()))
        )

        self.addParameter(
            QgsProcessingParameterCrs(
                self.SOURCE_CRS,
                self.tr('Source CRS'),
                defaultValue='EPSG:4326'
            )
        )

        self.addParameter(
            QgsProcessingParameterCrs(
                self.DESTINATION_CRS,
                self.tr('Destination CRS'),
                optional = True,
                defaultValue='ProjectCrs'
            )
        )

        # horizontal referred to flight direction => means wide angle
        parameter = QgsProcessingParameterNumber(self.HORIZONTAL_FOV,
                                                 self.tr('Wide camera angle'),
                                                 type = QgsProcessingParameterNumber.Double,
                                                 defaultValue = 84.0,
                                                 minValue = 0,
                                                 maxValue = 360)
        parameter.setFlags(parameter.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(parameter)

        # vertical referred to flight direction => means tall angle
        parameter = QgsProcessingParameterNumber(self.VERTICAL_FOV,
                                                 self.tr('Tall camera angle'),
                                                 type = QgsProcessingParameterNumber.Double,
                                                 defaultValue = 54.0,
                                                 minValue = 0,
                                                 maxValue = 360)
        parameter.setFlags(parameter.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(parameter)

        parameter = QgsProcessingParameterNumber(self.NADIR_TO_BOTTOM_OFFSET,
                                                 self.tr('Offset to add to bottom distance result'),
                                                 type = QgsProcessingParameterNumber.Double)
        parameter.setFlags(parameter.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(parameter)

        parameter = QgsProcessingParameterNumber(self.NADIR_TO_UPPPER_OFFSET,
                                                 self.tr('Offset to add to upper distance result'),
                                                 type = QgsProcessingParameterNumber.Double)
        parameter.setFlags(parameter.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(parameter)

    def processAlgorithm(self, parameters, context, feedback):
        input_layers = self.parameterAsLayerList(parameters, self.INPUT_LAYERS, context)

        camera_model = self.parameterAsEnum(parameters, self.CAMERA_MODEL, context)
        camera_model = list(self.CAMERA_DATA)[camera_model]
        camera_data = self.CAMERA_DATA[camera_model]

        sourceCRS = self.parameterAsCrs(parameters, self.SOURCE_CRS, context)
        if sourceCRS is None or not sourceCRS.isValid():
            sourceCRS = uavImagesFolder.crs()

        destinationCRS = self.parameterAsCrs(parameters, self.DESTINATION_CRS, context)
        if destinationCRS is None or not destinationCRS.isValid():
            feedback.pushInfo(self.tr('Getting destination CRS from source image'))
            destinationCRS = sourceCRS

        feedback.pushInfo(self.tr('Source CRS is: ')+self.tr(sourceCRS.authid()))
        feedback.pushInfo(self.tr('Destination CRS is: ')+self.tr(destinationCRS.authid()))

        # set fields for footprint and nadir vectors
        fields = QgsFields()
        fields.append(QgsField('date_time', QVariant.String))
        fields.append(QgsField('gimball_pitch', QVariant.Double))
        fields.append(QgsField('gimball_roll', QVariant.Double))
        fields.append(QgsField('gimball_jaw', QVariant.Double))
        fields.append(QgsField('relative_altitude', QVariant.Double))
        fields.append(QgsField('layer', QVariant.String))
        fields.append(QgsField('path', QVariant.String))
        fields.append(QgsField('camera_model', QVariant.String))
        fields.append(QgsField('camera_vertical_FOV', QVariant.Double))
        fields.append(QgsField('camera_horizontal_FOV', QVariant.Double))
        fields.append(QgsField('nadir_to_bottom_offset', QVariant.Double))
        fields.append(QgsField('nadir_to_upper_offset', QVariant.Double))

        (footprintSink, footprint_dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT_FOOTPRINTS,
            context,
            fields,
            QgsWkbTypes.Polygon,
            destinationCRS)
        if footprintSink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT_FOOTPRINTS))

        (nadirSink, nadir_dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT_NADIRS,
            context,
            fields,
            QgsWkbTypes.Point,
            destinationCRS)
        if nadirSink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT_NADIRS))

        # use tese params only if Camera modes is set to Advanced
        horizontalFOV = self.parameterAsDouble(parameters, self.HORIZONTAL_FOV, context)
        verticalFOV = self.parameterAsDouble(parameters, self.VERTICAL_FOV, context)
        nadirToBottomOffset = self.parameterAsDouble(parameters, self.NADIR_TO_BOTTOM_OFFSET, context)
        nadirToupperOffset = self.parameterAsDouble(parameters, self.NADIR_TO_UPPPER_OFFSET, context)

        self.CAMERA_DATA[camera_model]['horizontal_FOV'] = horizontalFOV
        self.CAMERA_DATA[camera_model]['vertical_FOV'] = verticalFOV
        self.CAMERA_DATA[camera_model]['nadir_to_bottom_offset'] = nadirToBottomOffset
        self.CAMERA_DATA[camera_model]['nadir_to_upper_offset'] = nadirToupperOffset

        # loop for each file
        progress_step = 100.0/len(input_layers)

        feedback.pushInfo("Going to process: {} images".format(len(input_layers)))
        for index, input_layer in enumerate(input_layers):
            try:
                index += 1

                if feedback.isCanceled():
                    return {}

                if isinstance(input_layer, str):
                    source = input_layer
                else:
                    source = input_layer.source()
                feedback.pushInfo("##### {}:Processing image: {}".format(index, source))

                # extract exif and XMP data
                try:
                    gdal.UseExceptions()
                    dataFrame = gdal.Open(source, gdal.GA_ReadOnly)
                    domains = dataFrame.GetMetadataDomainList()

                    # get exif metadata
                    exifTags = dataFrame.GetMetadata()
                    for key, value in exifTags.items():
                        #print(key, ':', value)
                        pass

                    # select metadata from XMP domain only
                    droneMetadata = {}
                    for domain in domains:
                        metadata = dataFrame.GetMetadata(domain)

                        # skip not relevant tags
                        if isinstance(metadata, dict):
                            for key, value in metadata.items():
                                #print(domain, "--", key, ":", value)
                                pass

                        # probably XMPs
                        if isinstance(metadata, list):
                            if domain == 'xml:XMP':
                                # parse xml
                                root = ElementTree.XML(metadata[0])
                                xmldict = XmlDictConfig(root)

                                # skip first element containing only description and domain info
                                subdict = list(xmldict.values())[0]

                                # get XMP tags
                                subdict = list(subdict.values())[0]
                                # parse XMP stuffs removing head namespace in the key 
                                # e.g.
                                #    {http://www.dji.com/drone-dji/1.0/}AbsoluteAltitude
                                # become
                                #    AbsoluteAltitude
                                for key, value in subdict.items():
                                    #print(domain, '--', key, value)
                                    key = key.split('}')[1]
                                    droneMetadata[key] = value

                except Exception as ex:
                    raise QgsProcessingException(str(ex))
                
                # extract all important tagged information about the image

                # get image lat/lon that will be the coordinates of nadir point
                # converted to destination CRS
                lat = _convert_to_degress(exifTags['EXIF_GPSLatitude'])
                emisphere = exifTags['EXIF_GPSLatitudeRef']
                lon = _convert_to_degress(exifTags['EXIF_GPSLongitude'])
                lonReference = exifTags['EXIF_GPSLongitudeRef']

                if emisphere == 'S':
                    lat = -lat
                if lonReference == 'W':
                    lon = -lon

                exifDateTime = exifTags['EXIF_DateTime']
                feedback.pushInfo("EXIF_DateTime: "+exifDateTime)

                exifImageWidth = exifTags['EXIF_PixelXDimension']
                exifImageLength = exifTags['EXIF_PixelYDimension']
                imageRatio = float(exifImageWidth)/float(exifImageLength)
                feedback.pushInfo("EXIF_PixelXDimension: "+exifImageWidth)
                feedback.pushInfo("EXIF_PixelYDimension: "+exifImageLength)
                feedback.pushInfo("Image ratio: "+str(imageRatio))

                # drone especific metadata
                droneMaker = exifTags['EXIF_Make']
                droneModel = exifTags['EXIF_Model']
                feedback.pushInfo("EXIF_Make: "+droneMaker)
                feedback.pushInfo("EXIF_Model: "+droneModel)

                # drone maker substitute XMP drone dictKey
                dictKey = droneMaker

                relativeAltitude = float(droneMetadata['RelativeAltitude'])
                feedback.pushInfo(self.tr("XMP {}:RelativeAltitude: ".format(dictKey))+str(relativeAltitude))

                gimballRoll = float(droneMetadata['GimbalRollDegree'])
                gimballPitch = float(droneMetadata['GimbalPitchDegree'])
                gimballYaw = float(droneMetadata['GimbalYawDegree'])
                feedback.pushInfo("XMP {}:GimbalRollDegree: ".format(dictKey)+str(gimballRoll))
                feedback.pushInfo("XMP {}:GimbalPitchDegree: ".format(dictKey)+str(gimballPitch))
                feedback.pushInfo("XMP {}:GimbalYawDegree: ".format(dictKey)+str(gimballYaw))

                flightRoll = float(droneMetadata['FlightRollDegree'])
                flightPitch = float(droneMetadata['FlightPitchDegree'])
                flightYaw = float(droneMetadata['FlightYawDegree'])
                feedback.pushInfo("XMP {}:FlightRollDegree: ".format(dictKey)+str(flightRoll))
                feedback.pushInfo("XMP {}:FlightPitchDegree: ".format(dictKey)+str(flightPitch))
                feedback.pushInfo("XMP {}:FlightYawDegree: ".format(dictKey)+str(flightYaw))

                feedback.pushInfo(self.tr("Horizontal FOV: ")+str(horizontalFOV))
                feedback.pushInfo(self.tr("Vertical FOV: ")+str(verticalFOV))

                # do calculation inspired by:
                # https://photo.stackexchange.com/questions/56596/how-do-i-calculate-the-ground-footprint-of-an-aerial-camera
                # distance of the nearest point to nadir (bottom distance)
                bottomDistance = relativeAltitude*(math.tan(math.radians(90 - gimballPitch - 0.5*verticalFOV)))
                # distance of the farest point to nadir (upper distance)
                upperDistance = relativeAltitude*(math.tan(math.radians(90 - gimballPitch + 0.5*verticalFOV)))

                feedback.pushInfo(self.tr("Northing (degree): ")+str(gimballYaw))
                feedback.pushInfo(self.tr("Nadir to bottom distance (metre): ")+str(bottomDistance))
                feedback.pushInfo(self.tr("Nadir to upper distance (metre): ")+str(upperDistance))

                # create base feature to add
                layerName = os.path.basename(source)
                layerName = os.path.splitext(layerName)[0]

                feature = QgsFeature(fields)
                feature.setAttribute('date_time', exifDateTime)
                feature.setAttribute('gimball_pitch', gimballPitch)
                feature.setAttribute('gimball_roll', gimballRoll)
                feature.setAttribute('gimball_jaw', gimballYaw)
                feature.setAttribute('relative_altitude', relativeAltitude)
                feature.setAttribute('layer', layerName)
                feature.setAttribute('path', source)
                feature.setAttribute('camera_model', droneModel)
                feature.setAttribute('camera_vertical_FOV', verticalFOV)
                feature.setAttribute('camera_horizontal_FOV', horizontalFOV)
                feature.setAttribute('nadir_to_bottom_offset', nadirToBottomOffset)
                feature.setAttribute('nadir_to_upper_offset', nadirToupperOffset)

                # populate nadir layer
                droneLocation = QgsPoint(lon, lat)
                tr = QgsCoordinateTransform(sourceCRS, destinationCRS, QgsProject.instance())
                droneLocation.transform(tr)
                feedback.pushInfo(self.tr("Nadir coordinates (lon, lat): ")+'{}, {}'.format(droneLocation.x(), droneLocation.y()))

                nadirGeometry = QgsGeometry.fromPointXY(QgsPointXY(droneLocation.x(), droneLocation.y()))
                feature.setGeometry(nadirGeometry)
                nadirSink.addFeature(feature, QgsFeatureSink.FastInsert)

                # create footprint to add to footprint sink
                feature = QgsFeature(feature)
                footprint = QgsGeometry.createWedgeBuffer(QgsPoint(droneLocation.x(), droneLocation.y()),
                                                        gimballYaw,
                                                        horizontalFOV,
                                                        abs(bottomDistance) + nadirToBottomOffset,
                                                        abs(upperDistance) + nadirToupperOffset)
                feature.setGeometry(footprint)
                footprintSink.addFeature(feature, QgsFeatureSink.FastInsert)

                feedback.setProgress(int(index*progress_step))
            except Exception as ex:
                exc_type, exc_obj, exc_trace = sys.exc_info()
                trace = traceback.format_exception(exc_type, exc_obj, exc_trace)
                raise QgsProcessingException(''.join(trace))

        # Return the results
        results = {
            self.OUTPUT_FOOTPRINTS: footprint_dest_id,
            self.OUTPUT_NADIRS: nadir_dest_id,
        }
        return results
