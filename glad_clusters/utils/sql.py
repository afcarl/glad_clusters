import psycopg2


def table_exists(conn, pg_schema, pg_table, commit=False):
    """ Check if a table exists

        Args:
            conn<psycopg2.connection>: Database connection
            pg_table<string>: Table name
    """
    cur = conn.cursor()
    try:
        sql = "SELECT * FROM {}.{} LIMIT 1;".format(pg_schema, pg_table)
        cur.execute(sql)
        exists = True
    except psycopg2.ProgrammingError:
        exists = False
    cur.close()

    if commit:
        conn.commit()

    return exists


def create_schema(conn, pg_schema, commit=False):
    """ Create working schema in PostgreSQL database

        Args:
            cur<psycopg2.cursor: Database cursor
            pg_schema<string>: Schema name
            commit<boolean(False)>: Make commit after statement
    """
    cur = conn.cursor()
    sql = "CREATE SCHEMA IF NOT EXISTS {}".format(pg_schema)
    cur.execute(sql)

    cur.close()

    if commit:
        conn.commit()
    return


def create_table(conn, pg_schema, pg_table, commit=False):
    """ Create export table in PostgreSQL database

        Args:
            cur<psycopg2.cursor: Database cursor
            pg_table<string>: Table name
            commit<boolean(False)>: Make commit after statement
    """
    cur = conn.cursor()
    sql = """
            CREATE TABLE {0}.{1}
                (
                index integer NOT NULL,
                count integer,
                area integer,
                min_date integer,
                max_date integer,
                longitude double precision,
                latitude double precision,
                z integer,
                x integer,
                y integer,
                i integer,
                j integer,
                file_name text,
                "timestamp" text,
                alerts integer[],
                CONSTRAINT {1}_pkey PRIMARY KEY (index)
                )
            WITH (
                OIDS=FALSE
                );

            SELECT AddGeometryColumn('{0}', '{1}', 'multipoint', 4326, 'MULTIPOINT', 3);
            SELECT AddGeometryColumn('{0}', '{1}', 'concave', 4326, 'POLYGON', 2);

            CREATE INDEX {1}_index_idx
                ON {0}.{1}
                USING btree
                (index);

            CREATE INDEX {1}_multipoint_idx
                ON {0}.{1}
                USING gist
                (multipoint);

            CREATE INDEX {1}_concave_idx
                ON {0}.{1}
                USING gist
                (concave);
    """.format(pg_schema, pg_table)
    cur.execute(sql)

    cur.close()

    if commit:
        conn.commit()

    return


def delete_data(conn, pg_schema, pg_table, commit=False):
    """ Delete all data from selected export table in PostgreSQL database

        Args:
            cur<psycopg2.cursor: Database cursor
            pg_table<string>: Table name
            commit<boolean(False)>: Make commit after statement
    """
    cur = conn.cursor()
    sql = "DELETE FROM {0}.{1};".format(pg_schema, pg_table)
    cur.execute(sql)

    cur.close()

    if commit:
        conn.commit()

    return


def load_data(conn, pg_schema, pg_table, filename, concave, commit=False):
    """
    Load data from into selected export table in PostgreSQL database.
    Make sure required functions exist and update geometries

        Args:
            cur<psycopg2.cursor: Database cursor
            pg_table<string>: Table name
            filename<string>: path and filename of CSV file
            commit<boolean(False)>: Make commit after statement
    """
    _unnest_2d_1d(conn)
    _sinh(conn)
    _load_csv(conn, pg_schema, pg_table, filename)
    _update_multipoint(conn, pg_schema, pg_table)
    _update_concave(conn, pg_schema, pg_table, concave)

    if commit:
        conn.commit()

    return


def _unnest_2d_1d(conn, commit=False):

    cur = conn.cursor()
    sql = """
    CREATE OR REPLACE FUNCTION unnest_2d_1d(anyarray)
        RETURNS SETOF anyarray AS
            $BODY$
            SELECT array_agg($1[d1][d2])
                FROM   generate_subscripts($1,1) d1
                    ,  generate_subscripts($1,2) d2
                GROUP  BY d1
                ORDER  BY d1
                $BODY$
        LANGUAGE sql IMMUTABLE
            COST 100
            ROWS 1000;
    """
    cur.execute(sql)

    cur.close()

    if commit:
        conn.commit()

    return


def _sinh(conn, commit=False):

    cur = conn.cursor()

    sql = """
    CREATE OR REPLACE FUNCTION sinh(x numeric)
        RETURNS double precision AS
        $BODY$
            BEGIN
                RETURN (exp(x) - exp(-x))/2;
            END;
        $BODY$
            LANGUAGE plpgsql VOLATILE
            COST 100;
    """
    cur.execute(sql)

    cur.close()

    if commit:
        conn.commit()
    return


def _load_csv(conn, pg_schema, pg_table, filename, commit=False):

    cur = conn.cursor()

    sql = """
    COPY {0}.{1}(index,count,area,min_date,max_date,longitude,latitude,z,x,y,i,j,file_name,timestamp,alerts) 
        FROM '{2}' DELIMITER ',' CSV HEADER;
    """.format(pg_schema, pg_table, filename)
    cur.execute(sql)

    cur.close()

    if commit:
        conn.commit()

    return


def _update_multipoint(conn, pg_schema, pg_table, commit=False):

    cur = conn.cursor()

    sql = """
        WITH t AS (SELECT "index" AS id, z, x, y, unnest_2d_1d(alerts) AS alerts FROM {0}.{1})
        UPDATE {0}.{1}
            SET multipoint = g.multipoint
        FROM
            (SELECT 
                id, 
                st_collect(
                ST_SetSRID(ST_MakePoint(
                    (360.0/(2^z))*(x+(alerts[2]/256.0))-180.0,
                    (atan(sinh((pi()*(1-(2*(y+(alerts[1]/256.0))/(2^z))))::numeric))*180.0)/pi(),
                    alerts[3]),
                4326)) AS multipoint
            FROM t
        GROUP BY id) AS g
        WHERE "index" = id;
    """.format(pg_schema, pg_table)
    cur.execute(sql)

    cur.close()

    if commit:
        conn.commit()
    return


def _update_concave(conn, pg_schema, pg_table, concave, commit=False):

    cur = conn.cursor()

    sql = """
    UPDATE {0}.{1}
        SET concave = 
        CASE 
            WHEN ST_GeometryType(ST_ConcaveHull(ST_Force2D(multipoint), {2})) != 'ST_Polygon' THEN
                St_Buffer(ST_ConcaveHull(ST_Force2D(multipoint), {2})::geography, 15)::geometry
            ELSE
                ST_ConcaveHull(ST_Force2D(multipoint), {2})
            END;
    """.format(pg_schema, pg_table, concave/100)
    cur.execute(sql)

    cur.close()

    if commit:
        conn.commit()

    return
