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
import math
import exifread
from libxmp.utils import file_to_dict

from qgis.core import (
    QgsPoint,
    QgsCoordinateReferenceSystem,
    QgsProject,
    QgsPointXY,
    QgsGeometry,
    QgsVectorLayer,
    QgsFeature
)

from camera_calculator import CameraCalculator


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

def _from_xmp(key, xmpDict):
    pass
    

imgpath = '/mnt/virtualmachines/INSITU/UAV/sample_images/Obligual/Lugo/DJI_0190.JPG'
# imgpath = '/mnt/virtualmachines/INSITU/UAV/sample_images/Obligual/As Pontes/DJI_0818.JPG'
#imgpath = '/mnt/virtualmachines/INSITU/UAV/sample_images/JorgeLama/f1757952.jpg'


image_crs = 'EPSG:4326'
local_utm = 'EPSG:25829'

exifTags = {}
with open(imgpath, 'rb') as f:
    exifTags = exifread.process_file(f)

lat = _convert_to_degress(exifTags['GPS GPSLatitude'])
emisphere = exifTags['GPS GPSLatitudeRef']
lon = _convert_to_degress(exifTags['GPS GPSLongitude'])
lonReference = exifTags['GPS GPSLongitudeRef']

if emisphere.values == 'S':
    lat = -lat
if lonReference.values == 'W':
    lon = -lon
print("geo Lat", lat)
print("geo Lon", lon)

# transfrom coord to best local UTM
droneLocation = QgsPoint(lon, lat)
sourceCrs = QgsCoordinateReferenceSystem(image_crs)
destCrs = QgsCoordinateReferenceSystem(local_utm)
tr = QgsCoordinateTransform(sourceCrs, destCrs, QgsProject.instance())
droneLocation.transform(tr)
print("utm Lat", droneLocation.y())
print("utm Lon", droneLocation.x())


#altitude_from_sealevel = exifTags['GPS GPSAltitude'].values[0].num / exifTags['GPS GPSAltitude'].values[0].den
realFocalLength = exifTags['EXIF FocalLength'].values[0].num / exifTags['EXIF FocalLength'].values[0].den
teoreticFocalLength = exifTags['EXIF FocalLengthIn35mmFilm'].values[0]
#print("GPSAltitude", GPSAltitude)
print("realFocalLength", realFocalLength)
print("35mmFocalLegth = ", teoreticFocalLength)

exifImageWidth = exifTags['EXIF ExifImageWidth'].values[0]
exifImageLength = exifTags['EXIF ExifImageLength'].values[0]
imageRatio = float(exifImageWidth)/float(exifImageLength)
print("exifImageWidth",exifImageWidth)
print("exifImageLength",exifImageLength)
print("imageRatio",imageRatio)

############################

xmp = file_to_dict( imgpath )
for k,v in xmp.items():
    #print(k,'--',v)
    pass
    
# look for drone tags
dictKey = None
for k in xmp.keys():
    if 'drone' in k:
        dictKey=k
        break

droneMetadata = {}
for tup in xmp[dictKey]:
    droneMetadata[tup[0]] = tup[1]

relativeAltitude = float(droneMetadata['drone-dji:RelativeAltitude'])
# relativeAltitude = 515.0
print('relativeAltitude', relativeAltitude)

gimballRoll = float(droneMetadata['drone-dji:GimbalRollDegree'])
gimballYaw = float(droneMetadata['drone-dji:GimbalYawDegree']) + 180
gimballPitch = float(droneMetadata['drone-dji:GimbalPitchDegree'])
# gimballPitch = -36
print('gimballPitch',gimballPitch)
print('gimballRoll',gimballRoll)
print('gimballYaw',gimballYaw)

flightRoll = float(droneMetadata['drone-dji:FlightRollDegree'])
flightYaw = float(droneMetadata['drone-dji:FlightYawDegree'])
flightPitch = float(droneMetadata['drone-dji:FlightPitchDegree'])
print('flightPitch',flightPitch)
print('flightRoll',flightRoll)
print('flightYaw',flightYaw)


diagonalFOV = 84.0
# use this FOV calculation if referred to 35mm diagonal FOV
fieldOfViewTall = diagonalFOV / (math.sqrt(1+math.pow(imageRatio, 2)))
fieldOfViewWide = diagonalFOV / (math.sqrt(1+math.pow(1.0/imageRatio, 2)))
# use this FOV calculation if use a fixed FOV
fieldOfViewTall = fieldOfViewWide = diagonalFOV

# use this if calculating FOV basing on focal lenght
#fieldOfViewWide = 2*math.degrees(math.atan(36.0/(2*teoreticFocalLength)))
#fieldOfViewTall = 2*math.degrees(math.atan(24.0/(2*teoreticFocalLength)))

print("fieldOfViewWide", fieldOfViewWide)
print("fieldOfViewTall", fieldOfViewTall)

#######################################################
# footprint calculation inspired bu:
# https://photo.stackexchange.com/questions/56596/how-do-i-calculate-the-ground-footprint-of-an-aerial-camera

# nadir disntance (by definition is 0)
d0 = 0
# distance of the nearest point to nadir
d1 = relativeAltitude*(math.tan(90 - gimballPitch - 0.5*fieldOfViewTall))
# distance of the farest point to nadir
d2 = relativeAltitude*(math.tan(90 - gimballPitch + 0.5*fieldOfViewTall))

print("Northing (degree)", gimballYaw)
print("       d0 (nadir)", d0)
print("d1 (m from nadir)", d1)
print("d2 (m from nadir)", d2)
#######################################################

c=CameraCalculator()
offsets=c.getBoundingPolygon(
    fieldOfViewTall,
    fieldOfViewWide, 
    relativeAltitude,
    gimballRoll,
    gimballPitch,
    gimballYaw)
# import ipdb; ipdb.set_trace()
for i, p in enumerate(offsets):
    print("point:", i, '-', p.x, p.y, p.z)

# create polygon
p0 = QgsPointXY(droneLocation.x() + offsets[0].x, droneLocation.y() + offsets[0].y)
p1 = QgsPointXY(droneLocation.x() + offsets[1].x, droneLocation.y() + offsets[1].y)
p2 = QgsPointXY(droneLocation.x() + offsets[2].x, droneLocation.y() + offsets[2].y)
p3 = QgsPointXY(droneLocation.x() + offsets[3].x, droneLocation.y() + offsets[3].y)

footprintGeometry = QgsGeometry.fromPolygonXY([[p0, p1, p2, p3, p0]])
footprintGeometry = QgsGeometry.fromPolygonXY([[p0, p2, p3, p1, p0]])

# create footprint layer with one polygon feature
footprintLayer = QgsVectorLayer('Polygon', 'footprint', 'memory' )
provider = footprintLayer.dataProvider()
feature = QgsFeature()
feature.setGeometry(footprintGeometry)
provider.addFeatures([feature])

# show it
QgsProject.instance().addMapLayer(footprintLayer)