import os
import numpy as np
from skimage import io
import matplotlib.pyplot as plt
from glad_clusters.clusters.processors import glad_between_dates
from glad_clusters.utils.service import ClusterService

DEFAULT_CENTROIDS=True
DEFAULT_CONVEXT_HULL=False
URL_TMPL='{}/{}/{}/{}.png'
SIZE=256
VALUE=1
VALUE_BAND=2
FIGSIZE=(4,4)
ROW_FIGSIZE=(18,3)
CLUSTER_MARKER='o'
CLUSTER_SIZE=20
CLUSTER_COLOR='r'
OVERLAY_ALPHA=0.75
CONVEX_HULL_COLOR='#00ccff'
#
#  
#
class ClusterViewer(object):
    """ ClusterViewer:
                
        Easily plot data from ClusterService.

        Args:
            service<cluster_service>: ClusterService instance
            url_base<str>: aws-bucket url for glad-tiles (defaults to environ['url'])        
    """
    @staticmethod
    def show(im=None,i=None,j=None,ax=None,alpha=1):
        if (i and j):
            if isinstance(i,int): 
                i=[i]
                j=[j]
            if ax:
                show=False
            else:
                show=True
                fig, ax = plt.subplots(1,1, figsize=FIGSIZE)
            if im is not None: ax.imshow(im,zorder=0,alpha=alpha)
            ax.scatter(j,i,
                marker=CLUSTER_MARKER,
                c=CLUSTER_COLOR,
                s=CLUSTER_SIZE,
                zorder=1)
            if show:
                plt.show()
        elif im is not None:
            if ax:
                ax.imshow(im,alpha=alpha)
            else:
                io.imshow(im)


    #
    # PUBLIC METHODS
    #
    def __init__(self,service,url_base=None):
        self.service=service
        self.url_base=url_base or os.environ.get('url')


    def tile(self,
            row_id=None,
            error=False,
            x=None,
            y=None,
            z=None,
            show=True,
            array=False):
        """ load tile directly from aws-bucket

            Note: This is the full GLAD tile and has not been filtered by dates.

            Args:

                Use one of the following to identify the tile:

                    row_id<int>: row id for a cluster on the tile of interest
                    z,x,y<int,int,int>: the z/x/y of the tile

                Other arguments:

                    show<bool[True]>: if true plot the image
                    array<bool[False]>: if true return the array
        """
        if row_id:
            if error: df=self.service.errors()
            else: df=self.service.dataframe(full=True)
            z,x,y=df[['z','x','y']].iloc[row_id]
        arr=io.imread(self._url(z,x,y))
        if show:
            ClusterViewer.show(arr)
        if array:
            return arr


    def input(self,row_id,centroids=DEFAULT_CENTROIDS,info=True):
        """ show the GLAD tile after filtering by date.

            Args:
                row_id<int>: row id for a cluster on the tile of interest
                centroids<bool[True]>: if true plot the cluster centroids
                info<bool[True]>: if true print the clusters data
        """
        rows=self.service.tile(row_id,full=True)
        nb_clusters,count,area,min_date,max_date=self.service.summary(rows)
        r=rows.iloc[0]
        arr=glad_between_dates(
                io.imread(self._url(r.z,r.x,r.y)),
                min_date,
                max_date)
        if centroids:
            clusters_i=rows.i.tolist()
            clusters_j=rows.j.tolist()
        else:
            clusters_i=None
            clusters_j=None
        if info:
            print("NB CLUSTERS: {}".format(rows.shape[0]))
            print("TOTAL COUNT: {}".format(count))
            print("TOTAL AREA: {}".format(area))
            print("DATES: {} to {}".format(min_date,max_date))
        ClusterViewer.show(arr,clusters_i,clusters_j)


    def cluster(self,
            row_id,
            centroids=DEFAULT_CENTROIDS,
            convex_hull=DEFAULT_CONVEXT_HULL,
            info=True):
        """ show the cluster

            Args:
                row_id<int>: row id for a cluster on the tile of interest
                centroids<bool[True]>: if true plot the cluster centroids
                convex_hull<bool[True]>: if true shade the convex_hull
                info<bool[True]>: if true print the cluster data
        """
        row=self.service.cluster(row_id,full=True)
        count,area,z,x,y,i,j,min_date,max_date=self._cluster_info(row)
        alerts=self._to_image(row.alerts)
        if info:
            print("COUNT: {}".format(count))
            print("AREA: {}".format(area))
            print("POINT: {},{}".format(i,j))
            print("ZXY: {}/{}/{}".format(z,x,y))
            print("DATES: {} to {}".format(min_date,max_date))
        if not centroids: i,j=None,None
        fig, ax = plt.subplots(1,1, figsize=FIGSIZE)
        if convex_hull:
            alpha=OVERLAY_ALPHA
            self._add_convex_hull(ax,row_id)
        else:
            alpha=1
        ClusterViewer.show(alerts,i,j,ax=ax,alpha=alpha)


    def clusters(self,
            start=None,
            end=None,
            row_ids=[],
            centroids=DEFAULT_CENTROIDS,
            convex_hull=DEFAULT_CONVEXT_HULL):
        """ show clusters
            
            Use one of the following:
                start,end<int,int>: the [start,end) range of rows to show
                row_ids<list>: list of row ids to show

            Other arguments:
                centroids<bool[True]>: if true plot the cluster centroids
                convex_hull<bool[True]>: if true shade the convex_hull
        """
        if row_ids:
            rows=self.service.dataframe(full=True).iloc[row_ids]
        else:
            rows=self.service.dataframe(full=True)[start:end]

        fig, axs = plt.subplots(1,rows.shape[0], figsize=ROW_FIGSIZE)
        i=0
        for row_id,row in rows.iterrows():
            self._cluster_axis(axs[i],row,centroids,convex_hull)
            i+=1
        plt.show()


    #
    # INTERNAL METHODS
    #
    def _cluster_info(self,row):
        min_date,max_date=ClusterService.int_to_str_dates(
                row.min_date,
                row.max_date)
        return (
            row['count'],
            row.area,
            row.z,row.x,row.y,
            row.i,row.j,
            min_date,max_date)


    def _add_convex_hull(self,ax,row_id=None,alerts=None):
        ch=self.service.convex_hull(row_id,alerts)
        ax.fill(ch[:,1],ch[:,0],
            c=CONVEX_HULL_COLOR,
            zorder=-1)


    def _cluster_axis(self,ax,row,centroids,convex_hull):
        count,area,z,x,y,i,j,min_date,max_date=self._cluster_info(row)
        alerts=self._to_image(row.alerts)
        title='count:{}, area:{}, pt:{},{}'.format(count,area,i,j)
        subtitle='dates: {}, {}'.format(min_date,max_date)
        if not centroids: i,j=None,None                
        if convex_hull:
            alpha=OVERLAY_ALPHA
            self._add_convex_hull(ax,alerts=row.alerts)
        else:
            alpha=1
        ClusterViewer.show(alerts,i,j,ax=ax,alpha=alpha)
        ax.scatter([j],[i],marker='o',c='r',s=20)
        ax.set_title(title)
        ax.set_xlabel(subtitle)



    def _to_image(self,data):
        data=data.astype(int)
        im=np.zeros((SIZE,SIZE))
        nb_bands=data.shape[1]
        if nb_bands==2:
            im[data[:,0],data[:,1]]=VALUE
        else:
            im[data[:,0],data[:,1]]=data[:,VALUE_BAND]
        return im


    def _url(self,z,x,y):
        return URL_TMPL.format(self.url_base,z,x,y)


