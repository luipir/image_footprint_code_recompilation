DROP TABLE IF EXISTS chp07.viewshed;
CREATE TABLE chp07.viewshed AS
SELECT 1 AS gid, roll, pitch, heading,
  chp07.pbr(ST_Force3D(geom),
        radians(pitch)::numeric,
        radians(jaw)::numeric,
        radians(roll)::numeric,
        radians(fovtall)::numeric,
        radians(fovwide)::numeric,
        ( (3.2808399 * altitude) - 838)::numeric)
  AS the_geom FROM uas_locations;
