# -*- coding: utf-8 -*-
"""
***************************************************************************
    uav_footprint.py
    ---------------------
    Date                 : August 2019
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

import time
import math
import exifread
from libxmp.utils import file_to_dict

from qgis.PyQt.QtCore import (QCoreApplication,
                              QVariant)
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingException,
                       QgsProcessingParameterDefinition,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterVectorDestination,
                       QgsProcessingParameterRasterLayer,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterCrs,
                       QgsProcessingParameterBoolean,
                       QgsProcessingUtils,
                       QgsProcessingFeatureSourceDefinition,
                       QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform,
                       QgsProject,
                       QgsPointXY,
                       QgsPoint,
                       QgsGeometry,
                       QgsVectorLayer,
                       QgsFeature,
                       QgsWkbTypes,
                       QgsFeatureSink,
                       QgsField,
                       QgsFields,
                       QgsWkbTypes)
import processing

def _convert_to_degress(value):
    """
    Helper function to convert the GPS coordinates stored in the EXIF to degress in float format
    :param value:
    :type value: exifread.utils.Ratio
    :rtype: float
    """
    d = float(value.values[0].num) / float(value.values[0].den)
    m = float(value.values[1].num) / float(value.values[1].den)
    s = float(value.values[2].num) / float(value.values[2].den)

    return d + (m / 60.0) + (s / 3600.0)

class UAVImageFootprint(QgsProcessingAlgorithm):

    INPUT = 'INPUT'
    OUTPUT_NADIR = 'OUTPUT_NADIR'
    OUTPUT_FOOTPRINT = 'OUTPUT_FOOTPRINT'

    HORIZONTAL_FOV = 'HORIZONTAL_FOV'
    VERTICAL_FOV = 'VERTICAL_FOV'
    USE_IMAGE_RATIO_FOR_VERTICAL_FOV = 'USE_IMAGE_RATIO_FOR_VERTICAL_FOV'
    VERTICAL_FOV_MULTIPLIER = 'VERTICAL_FOV_MULTIPLIER'
    SOURCE_CRS = 'SOURCE_CRS'
    DESTINATION_CRS = 'DESTINATION_CRS'
    NADIR_TO_BOTTOM_OFFSET = 'NADIR_TO_BOTTOM_OFFSET'
    NADIR_TO_UPPPER_OFFSET = 'NADIR_TO_UPPPER_OFFSET'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return UAVImageFootprint()

    def group(self):
        return self.tr('UAV tools')

    def groupId(self):
        return 'Image footprint'

    def __init__(self):
        super().__init__()

    def name(self):
        return 'uavimagefootprint'

    def displayName(self):
        return self.tr('UAV image footprint')

    def shortHelpString(self):
        return self.tr('TODO')

    def initAlgorithm(self, config=None):

        self.addParameter(
            QgsProcessingParameterRasterLayer(self.INPUT,
                                              self.tr('Input image'))
        )

        self.addParameter(
            QgsProcessingParameterVectorDestination (
                self.OUTPUT_FOOTPRINT,
                self.tr('Image footprint'),
                QgsProcessing.TypeVectorPolygon
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink (
                self.OUTPUT_NADIR,
                self.tr('Drone nadir point'),
                QgsProcessing.TypeVectorPoint
            )
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

        # horizontar referred to flight direction => means wide angle
        self.addParameter(
            QgsProcessingParameterNumber(
                self.HORIZONTAL_FOV,
                self.tr('Wide camera angle'),
                type = QgsProcessingParameterNumber.Double,
                defaultValue = 84.0,
                minValue = 0,
                maxValue = 360
            )
        )

        # vertical referred to flight direction => means tall angle
        parameter = QgsProcessingParameterNumber(self.VERTICAL_FOV,
                                                 self.tr('Tall camera angle'),
                                                 type = QgsProcessingParameterNumber.Double,
                                                 defaultValue = 54.0,
                                                 minValue = 0,
                                                 maxValue = 360)
        parameter.setFlags(parameter.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(parameter)

        parameter = QgsProcessingParameterBoolean(self.USE_IMAGE_RATIO_FOR_VERTICAL_FOV,
                                                  self.tr('Calc Vertical FOV using image ratio'),
                                                  defaultValue = True)
        parameter.setFlags(parameter.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(parameter)

        parameter = QgsProcessingParameterNumber(self.VERTICAL_FOV_MULTIPLIER,
                                                 self.tr('Empiric multiplier to fix tall FOV basing on image ratio'),
                                                 type = QgsProcessingParameterNumber.Double,
                                                 defaultValue = 0.855)
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
        uavImage = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        feedback.pushInfo(self.tr('Processing image source: ')+self.tr(uavImage.source()))

        sourceCRS = self.parameterAsCrs(parameters, self.SOURCE_CRS, context)
        if sourceCRS is None or not sourceCRS.isValid():
            sourceCRS = uavImage.crs()

        destinationCRS = self.parameterAsCrs(parameters, self.DESTINATION_CRS, context)
        if destinationCRS is None or not destinationCRS.isValid():
            feedback.pushInfo(self.tr('Getting destination CRS from source image'))
            destinationCRS = sourceCRS

        feedback.pushInfo(self.tr('Source CRS is: ')+self.tr(sourceCRS.authid()))
        feedback.pushInfo(self.tr('Destination CRS is: ')+self.tr(destinationCRS.authid()))

        # set fields for footprint and nadir vectors
        fields = QgsFields()
        # fields.append(QgsField('gimball_pitch', QVariant.Double))
        # fields.append(QgsField('gimball_roll', QVariant.Double))
        # fields.append(QgsField('gimball_jaw', QVariant.Double))
        # fields.append(QgsField('relative_altitude', QVariant.Double))
        # fields.append(QgsField('image', QVariant.String))
        # fields.append(QgsField('camera_model', QVariant.String))
        # fields.append(QgsField('camera_vertical_FOV', QVariant.Double))
        # fields.append(QgsField('camera_horizontal_FOV', QVariant.Double))

        # (footprintSink, footprint_dest_id) = self.parameterAsSink(
        #     parameters,
        #     self.OUTPUT_FOOTPRINT,
        #     context,
        #     fields,
        #     QgsWkbTypes.Polygon,
        #     destinationCRS)
        # if footprintSink is None:
        #     raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT_FOOTPRINT))

        (nadirSink, nadir_dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT_NADIR,
            context,
            fields,
            QgsWkbTypes.Point,
            destinationCRS)
        if nadirSink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT_NADIR))

        horizontalFOV = self.parameterAsDouble(parameters, self.HORIZONTAL_FOV, context)
        verticalFOV = self.parameterAsDouble(parameters, self.VERTICAL_FOV, context)
        useImageRatio = self.parameterAsBoolean(parameters, self.USE_IMAGE_RATIO_FOR_VERTICAL_FOV, context)
        verticalFOV_multiplier = self.parameterAsDouble(parameters, self.VERTICAL_FOV_MULTIPLIER, context)

        nadirToBottomOffset = self.parameterAsDouble(parameters, self.NADIR_TO_BOTTOM_OFFSET, context)
        nadirToupperOffset = self.parameterAsDouble(parameters, self.NADIR_TO_UPPPER_OFFSET, context)

        # extract exif and XMP data
        try:
            exifTags = {}
            with open(uavImage.source(), 'rb') as f:
                exifTags = exifread.process_file(f)

            # TODO: use pure XML parsing method
            xmp = file_to_dict( uavImage.source() )
            dictKey = None
            for k in xmp.keys():
                if 'drone' in k:
                    dictKey=k
                    break

            droneMetadata = {}
            for tup in xmp[dictKey]:
                droneMetadata[tup[0]] = tup[1]

        except Exception as ex:
            raise QgsProcessingException(str(ex))
        
        # extract all important tagged information about the image

        # get image lat/lon that will be the coordinates of nadir point
        # converted to destination CRS
        lat = _convert_to_degress(exifTags['GPS GPSLatitude'])
        emisphere = exifTags['GPS GPSLatitudeRef']
        lon = _convert_to_degress(exifTags['GPS GPSLongitude'])
        lonReference = exifTags['GPS GPSLongitudeRef']

        if emisphere.values == 'S':
            lat = -lat
        if lonReference.values == 'W':
            lon = -lon

        exifImageWidth = exifTags['EXIF ExifImageWidth'].values[0]
        exifImageLength = exifTags['EXIF ExifImageLength'].values[0]
        imageRatio = float(exifImageWidth)/float(exifImageLength)
        feedback.pushInfo("EXIF ExifImageWidth: "+str(exifImageWidth))
        feedback.pushInfo("EXIF ExifImageLength: "+str(exifImageLength))
        feedback.pushInfo("Image ratio: "+str(imageRatio))

        relativeAltitude = float(droneMetadata['drone-dji:RelativeAltitude'])
        feedback.pushInfo(self.tr("XMP {}:RelativeAltitude: ".format(dictKey))+str(relativeAltitude))

        gimballRoll = float(droneMetadata['drone-dji:GimbalRollDegree'])
        gimballPitch = float(droneMetadata['drone-dji:GimbalPitchDegree'])
        gimballYaw = float(droneMetadata['drone-dji:GimbalYawDegree'])
        feedback.pushInfo("XMP {}:GimbalRollDegree: ".format(dictKey)+str(gimballRoll))
        feedback.pushInfo("XMP {}:GimbalPitchDegree: ".format(dictKey)+str(gimballPitch))
        feedback.pushInfo("XMP {}:GimbalYawDegree: ".format(dictKey)+str(gimballYaw))

        flightRoll = float(droneMetadata['drone-dji:FlightRollDegree'])
        flightPitch = float(droneMetadata['drone-dji:FlightPitchDegree'])
        flightYaw = float(droneMetadata['drone-dji:FlightYawDegree'])
        feedback.pushInfo("XMP {}:FlightRollDegree: ".format(dictKey)+str(flightRoll))
        feedback.pushInfo("XMP {}:FlightPitchDegree: ".format(dictKey)+str(flightPitch))
        feedback.pushInfo("XMP {}:FlightYawDegree: ".format(dictKey)+str(flightYaw))

        feedback.pushInfo(self.tr("Horizontal FOV: ")+str(horizontalFOV))
        if useImageRatio:
            verticalFOV = (horizontalFOV/imageRatio)*verticalFOV_multiplier
            feedback.pushInfo(self.tr("Vertical FOV basing on image ratio: ")+str(verticalFOV))
        else:
            feedback.pushInfo(self.tr("Vertical FOV: ")+str(verticalFOV))

        # do calculation
        # distance of the nearest point to nadir (bottom distance)
        bottomDistance = relativeAltitude*(math.tan(math.radians(90 - gimballPitch - 0.5*verticalFOV)))
        # distance of the farest point to nadir (upper distance)
        upperDistance = relativeAltitude*(math.tan(math.radians(90 - gimballPitch + 0.5*verticalFOV)))

        feedback.pushInfo(self.tr("Northing (degree): ")+str(gimballYaw))
        feedback.pushInfo(self.tr("Nadir to bottom distance (metre): ")+str(bottomDistance))
        feedback.pushInfo(self.tr("Nadir to upper distance (metre): ")+str(upperDistance))

        # populate nadir layer
        droneLocation = QgsPoint(lon, lat)
        tr = QgsCoordinateTransform(sourceCRS, destinationCRS, QgsProject.instance())
        droneLocation.transform(tr)
        feedback.pushInfo(self.tr("Nadir coordinates (lon, lat): ")+'{}, {}'.format(droneLocation.x(), droneLocation.y()))

        nadirGeometry = QgsGeometry.fromPointXY(QgsPointXY(droneLocation.x(), droneLocation.y()))
        feature = QgsFeature()
        feature.setGeometry(nadirGeometry)
        nadirSink.addFeature(feature, QgsFeatureSink.FastInsert)

        # create a memory layer with nadir point to be input to "native:wedgebuffers" algorithm
        # it's not possible to use directly the FeatureSink becaseu can't be accepted by processing.run.
        # the reason is that a generic sink can be also NOT a layer but a more generic sink where features
        # can't be recovered.
        tempNadirLayer = QgsVectorLayer('Point?crs={}'.format(destinationCRS.authid()), 'tempNadirLayer', 'memory' )
        provider = tempNadirLayer.dataProvider()
        feature = QgsFeature()
        feature.setGeometry(nadirGeometry)
        provider.addFeatures([feature])

        # create polygon using wedge buffer processign algorithm
        parameters = {
            'INPUT': tempNadirLayer,
            'AZIMUTH': gimballYaw,
            'WIDTH': horizontalFOV,
            'OUTER_RADIUS': abs(bottomDistance) + nadirToBottomOffset,
            'INNER_RADIUS': abs(upperDistance) + nadirToupperOffset,
            'OUTPUT': parameters[self.OUTPUT_FOOTPRINT]
        }
        wedge_buffer_result = processing.run("native:wedgebuffers", 
                                            parameters,
                                            is_child_algorithm=True,
                                            context = context,
                                            feedback = feedback)

        # Return the results
        results = {
            self.OUTPUT_FOOTPRINT: wedge_buffer_result['OUTPUT'],
            self.OUTPUT_NADIR: nadir_dest_id,
        }
        return results
