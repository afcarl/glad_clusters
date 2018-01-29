import os
import math
import itertools
import json
import boto3
from boto3.dynamodb.conditions import Attr
import numpy as np
import pandas as pd
import utils.multiprocess as mp


DEFAULT_START_DATE='2015-01-01'
DEFAULT_END_DATE='2025-01-01'
DEFAULT_MIN_COUNT=25
DEFAULT_WIDTH=5
DEFAULT_ITERATIONS=25
DEFAULT_ZOOM=12
DELETE_RESPONSES=False
DEFAULT_TABLE=os.environ.get('table')
LAMBDA_FUNCTION_NAME='gfw-glad-clusters-v1-dev-meanshift'

DATAFRAME_COLUMNS=[
    'count',
    'area',
    'min_date',
    'max_date',
    'latitude',
    'longitude',
    'z','x','y','i','j',
    'file_name',
    'timestamp',
    'alerts',
    'input_data']


VIEW_COLUMNS=[
    'timestamp',
    'count',
    'area',
    'min_date',
    'max_date',
    'latitude',
    'longitude',
    'x','y']


class ClusterService(object):


    #
    #  PUBLC METHODS
    #    
    def __init__(self,
            bounds=None,
            tile_bounds=None,
            lat=None,
            lon=None,
            x=None,
            y=None,
            start_date=DEFAULT_START_DATE,
            end_date=DEFAULT_END_DATE,
            min_count=DEFAULT_MIN_COUNT,
            width=DEFAULT_WIDTH,
            iterations=DEFAULT_ITERATIONS,
            z=DEFAULT_ZOOM,
            table=DEFAULT_TABLE):
        self._init_properties()
        self.start_date=DEFAULT_START_DATE
        self.end_date=DEFAULT_END_DATE
        self.min_count=min_count
        self.width=width
        self.iterations=iterations
        self.z=z
        self._N=(2**self.z)
        self.table=table
        self._set_tile_bounds(bounds,tile_bounds,lat,lon,x,y)
        

    def fetch(self,key=None,query=None,**kwargs):
        """ fetch clusters from dynamodb 
        """
        db=boto3.resource('dynamodb')
        print(self.table)
        table=db.Table(self.table)
        if key:
            self.responses=[table.get_item(Key=key)]
        else:
            if query or kwargs:
                filter_expression=self._db_filter(query or kwargs)
            else:
                filter_expression=self._build_filter()
            rows=table.scan(FilterExpression=filter_expression)
            self.responses=rows.get('Items')


    def run(self):
        """ find clusters on tiles
        
            NOTE: if (self.x and self.y): 
                    pass directly to _run_tile
                  else:
                    use multiprocessing
        """
        self.lambda_client=boto3.client('lambda')
        if (self.x and self.y):
            self.responses=[self._run_tile()]
        else:
            xys=itertools.product(
                range(self.x_min,self.x_max+1),
                range(self.y_min,self.y_max+1))
            self.responses=mp.map_with_threadpool(self._run_tile,list(xys))

    
    def dataframe(self):
        """ return data frame of clusters data
            
            NOTE: if DELETE_RESPONSES is True
                  responses json will be removed
        """
        if  self._dataframe is None:
            self._dataframe=pd.DataFrame(
                self._dataframe_rows(),
                columns=DATAFRAME_COLUMNS)
            self._dataframe.sort_values(
                'timestamp',
                ascending=False,
                inplace=True)
            if DELETE_RESPONSES: self.responses=None
        return self._dataframe


    def view(self):
        """ return only VIEW_COLUMNS of .dataframe()
            * excludes data arrays, i and j, ...
        """
        return self.dataframe()[VIEW_COLUMNS]


    def cluster(self,
            row_id=None,
            lat=None,lon=None,
            z=None,x=None,y=None,i=None,j=None,
            timestamp=None,
            ascending=False,
            as_view=True):
        """ fetch cluster data

            Convince method for selecting row of dataframe
            
            Args:
                row_id<int>: dataframe index for cluster
                lat,lon<floats>: latitude,longitude for cluster
                z,x,y,i,j<ints>: tile/pixel location for cluster
                timestamp<str>: timestamp for cluster (consider using row_id)
                ascending<bool>: 
                    if true sort by ascending time and grab first matching row
                as_view:
                    if true return only VIEW_COLUMNS. 
                    else include all columns (including input/alerts data)
        """
        if self._not_none([row_id]):
            row=self.dataframe().iloc[row_id]
        else:
            test=True
            if self._not_none([lat,lon]):
                test=test & (
                    (self.dataframe().latitude==lat) & 
                    (self.dataframe().longitude==lon))
            elif self._not_none([x,y,z]):
                test=test & (
                    (self.dataframe().z==z) & 
                    (self.dataframe().x==x) & 
                    (self.dataframe().y==y))
            if timestamp:
                test=test & (self.dataframe().timestamp==timestamp)
            rows=self.dataframe()[test]
            if ascending: rows.sort_values('timestamp',inplace=True)
            row=rows.iloc[0]
        if as_view:
            return row[VIEW_COLUMNS]
        else:
            return row


    #
    #  INTERNAL METHODS
    #
    def _init_properties(self):
        self.x=None
        self.y=None
        self._dataframe=None


    def _db_filter(self,query):
        keys=query.keys()
        key0=keys.pop()
        db_filter=Attr(key0).eq(query[key0])
        for key in keys:
            db_filter&=Attr(key).eq(query[key])
        return db_filter


    def _build_filter(self):
        db_filter=Attr('z').eq(self.z)
        if self.start_date:
            db_filter &= Attr('start_date').gte(self.start_date)
        if self.end_date:
            db_filter &= Attr('end_date').lte(self.end_date)
        if self.min_count:
            db_filter &= Attr('min_count').eq(self.min_count)
        if self.width:
            db_filter &= Attr('width').eq(self.width)
        if self.iterations:
            db_filter &= Attr('iterations').eq(self.iterations)
        return db_filter


    def _request_data(self,x,y):
        return json.dumps({
            "z":self.z,
            "x":x,
            "y":y,
            "start_date":self.start_date,
            "end_date":self.end_date,
            "min_count":self.min_count,
            "width":self.width,
            "iterations":self.iterations })

    
    def _set_tile_bounds(self,bounds,tile_bounds,lat,lon,x,y):
        """
            NOTE: if a single pair (x,y) or (lat,lon) the x,y-values 
            will be set for the find_by_tile method.
        """
        if bounds:
            tile_bounds=[self._latlon_to_xy(*latlon) for latlon in bounds]
        elif (lat and lon):
            self.x,self.y=self._latlon_to_xy(lat,lon)
            tile_bounds=[[self.x,self.y],[self.x,self.y]]
        elif (x and y):
            self.x=x
            self.y=y
            tile_bounds=[[self.x,self.y],[self.x,self.y]]
        tile_bounds=np.array(tile_bounds)
        self.x_min,self.y_min=tile_bounds.min(axis=0)
        self.x_max,self.y_max=tile_bounds.max(axis=0)
            
            
    def _latlon_to_xy(self,lat,lon):
        lat_rad=math.radians(lat)
        x=self._N*(lon+180.0)/360
        y=self._N*(1.0-math.log(math.tan(lat_rad)+(1/math.cos(lat_rad)))/math.pi)/2.0
        return int(x),int(y)
    
    
    def _lat(self,z,x,y,i,j):
        """ TODO CONVERT zxyij to LAT """
        return -999


    def _lon(self,z,x,y,i,j):
        """ TODO CONVERT zxyij to LAT """
        return -999


    def _process_response(self,response):
        return json.loads(response['Payload'].read())


    def _run_tile(self,location=None,x=None,y=None):
        """ find clusters on tile
        
            NOTE: if no args are passed it will attempt to use 
                  the x,y (or lat,lon) passed in the constructor
        
            Args:
                location<tuple>: tile-xy value (x,y)
                x<int>: tile x value
                y<int>: tile y value
        """
        if location: x,y=location
        if not (x and y):
            x=self.x
            y=self.y
        if (x and y):
            response=self.lambda_client.invoke(
                FunctionName=LAMBDA_FUNCTION_NAME,
                InvocationType='RequestResponse',
                LogType='Tail',
                Payload=self._request_data(x,y))
            return self._process_response(response)


    def _dataframe_rows(self):
        dfrows=[]
        for response in self.responses:
            z=response.get('z')
            x=response.get('x')
            y=response.get('y')
            for cluster in response.get('data',{}).get('clusters',[]):
                i=cluster.get('i')
                j=cluster.get('j')
                dfrows.append([
                        cluster.get('count'),
                        cluster.get('area'),
                        cluster.get('min_date'),
                        cluster.get('max_date'),
                        self._lat(z,x,y,i,j),
                        self._lon(z,x,y,i,j),
                        z,x,y,i,j,
                        response['file_name'],
                        response['timestamp'],
                        np.array(cluster.get('alerts')).astype(int),
                        np.array(response['data']['input_data']).astype(int)])
        return dfrows


    def _not_none(self,values):
        test=[ (val is not None) for val in values ]
        return np.prod(test).astype(bool)

