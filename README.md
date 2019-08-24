# Image Footprint Code Recompilation
Code portings and code recompilations os way to calc Image footprints (e.g. from UAV)

this recompilation has been sponsored by Ingenieria INSITU SL https://ingenieriainsitu.com/

## sources

### For PostGIS Cookbook

see relative directory

### For CameraCalculator.java

Is a 1to1 python porting of the java code:

    https://github.com/zelenmi6/thesis/blob/master/src/geometry/CameraCalculator.java

referred in:

    https://stackoverflow.com/questions/38099915/calculating-coordinates-of-an-oblique-aerial-image

The only part not ported are that explicetly abandoned or not used at all by the main call to getBoundingPolygon method.

by: milan zelenka:

    * https://github.com/zelenmi6

    * https://stackoverflow.com/users/6528363/milan-zelenka
