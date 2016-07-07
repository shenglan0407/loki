import numpy as np
from scipy.ndimage import zoom

class RingFetch:
    def __init__(self, a, b, img, mask=None, q_resolution=0.05, 
                    phi_resolution=0.5,wavelen=1.41, pixsize=0.00005, 
                    detdist=0.051, photon_conversion_factor=1):
        '''
        Description
        ===========
        Sums the intensities in a diffraction image to form effective pixel
        readouts at a specified resolution.

        Parameters
        ==========

        `a`, `b` is the horizontal, vertical pixel coordinate where
            forward beam intersects detector
        
        `img` is a two-dimensional diffraction image with ring patterns

        `mask` is a boolean array where False,True represent masked,
            unmasked pixels in an image.
        
        `q_resolution`, `phi_resolution` are desired resolutions of
            one-dimensional output ring in radial, azimuthal 
            dimensions (inverse Angstrom and degree units, respectively)
        
        `wavelen`, `pixsize`, `detdist` are photon-wavelength, pixel-size 
            (assuming square pixels) and sample-to-detector-distance in 
            Angstrom, meter, and meter units, respectively.
        '''
        
        self.a = a
        self.b = b
        self.img = img
        self.q_resolution = q_resolution
        self.phi_resolution = phi_resolution
        self.num_phi_nodes =  int ( 360.  / self.phi_resolution)

        if mask is not None:
            assert(mask.shape == self.img.shape)
        self.mask = mask
       
        self._set_max_ring_radius()

#       convert pixel radius to q
        self.r2q = lambda R: np.sin( np.arctan(R*pixsize/detdist)/2.) \
                                *4*np.pi/wavelen
#       ... and vice versa
        self.q2r = lambda Q: np.tan( 2*np.arcsin(Q*wavelen/4/np.pi)) \
                                *detdist/pixsize

        self.r2theta = lambda R: np.arctan( R*pixsize / detdist  )/2.
    
        self.photon_conversion_factor = photon_conversion_factor

    def _set_max_ring_radius(self):
        possible_max_radii = (self.img.shape[1] - self.a, 
                              self.a , 
                              self.img.shape[0]-self.b, 
                              self.b)
        self.maximum_allowable_ring_radius = np.min( possible_max_radii)
        
   
    def update_working_image( self, img ):
        assert ( img.shape == self.img.shape )
        self.img = img

###############
# MAIN METHOD #
###############
    def fetch_a_ring(self, ring_radius, solid_angle=True):
        '''
        Parameters
        ==========
        
        `ring_radius` is radius of ring in pixel units

        `solid_angle` is whether or not to do the solid angle correction

        Returns
        =======
       
        A tuple of ( `phi_values`, `polar_ring_final`)

        `phi_values` are the azimuthal centers to the effective pixels 
            at the desired resolution

        `polar_ring_final` is the corresponding intensities in the 
            effective pixels
        '''
        
        self._define_radial_extent_of_ring(ring_radius)
        self._check_ring_edges()
        self._make_output_containers()
        self._iterate_across_ring_extent()
        if solid_angle:
            self._solid_angle_correction()
        self._adjust_fractional_rings()
        return self.ring_output.sum(0)

    def _define_radial_extent_of_ring(self, ring_radius):
        q_of_ring = self.r2q(ring_radius)
#       min q for ring at desired resolution
        qmin = q_of_ring - self.q_resolution/2. 
#       max q for ring at desired resolution
        qmax = q_of_ring + self.q_resolution/2.
#       qmin/qmax in radial pixle units
        self.rmin = self.q2r(qmin)
        self.rmax = self.q2r(qmax)
        assert( self.rmax-1. > self.rmin)
        
        self.radii = np.arange( int(self.rmin), int(self.rmax)+1 )
        self.nrad = len( self.radii)

    def _check_ring_edges(self):
        nphi_min = int( 2 * np.pi * self.rmin )
        assert(nphi_min >= self.num_phi_nodes)
        assert( int(self.rmax)+1 < self.maximum_allowable_ring_radius)
    
    def _make_output_containers(self):
        self.ring_output = np.zeros( ( self.nrad, self.num_phi_nodes) )

    def _iterate_across_ring_extent(self):
        for self.rad_ind, radius in enumerate( self.radii):
#           number of azimuthal points in radial image
            self.nphi = int( 2*np.pi*radius) 
            self.InterpSimp = InterpSimple(self.a, self.b, radius+1,
                                radius, self.nphi, raw_img_shape=self.img.shape)
            self._set_polar_ring()
            self._fill_in_masked_values()
            self._sum_intensity_in_azimuthal_nodes()


    def _solid_angle_correction(self):
        theta_vals = self.r2theta(self.radii)
        solid_angle_per_radii = np.cos( theta_vals) **3
        self.ring_output *= solid_angle_per_radii[:,None]
    
    def _adjust_fractional_rings(self):
        start_factor = 1. - self.rmin + np.floor( self.rmin)
        stop_factor = self.rmax - np.floor( self.rmax )
        self.ring_output[0] *= start_factor
        self.ring_output[-1] *= stop_factor
        
################################
# RING RADII ITERATION METHODS #
################################
    def _set_polar_ring(self):
        polar_img = self.InterpSimp.nearest(self.img)
        self.polar_ring = polar_img[0]
            
    def _fill_in_masked_values(self):
        if self.mask is not None:
#           interpolate the polar mask
            polar_mask = self.InterpSimp.nearest(self.mask.astype(int))
            self.polar_ring_mask = polar_mask[0]
            self._fill_polar_ring()
  
    def _sum_intensity_in_azimuthal_nodes(self):
            node_edges = np.linspace(0, self.nphi, self.num_phi_nodes+1) # fractional pixels
            node_inds = node_edges.astype(int)
            frac_start = (1 - node_edges + np.floor(node_edges))[:-1]
            frac_stop = (node_edges - np.floor(node_edges))[1:]
            for i in xrange(self.num_phi_nodes-1):
                start = node_inds[i]
                stop = node_inds[i+1]
                summed_intens = self.polar_ring[start] * frac_start[i] \
                                + np.sum(self.polar_ring[start+1:stop])\
                                + self.polar_ring[stop] * frac_stop[i]
                self.ring_output[self.rad_ind,i] += summed_intens \
                                            * self.photon_conversion_factor
            start = node_inds[-2]
            self.ring_output[self.rad_ind, -1] += (self.polar_ring[start] * frac_start[-1] \
                                            + np.sum(self.polar_ring[start+1:]))\
                                            * self.photon_conversion_factor
    
########################################
# METHODS FOR FILLLING IN MASKED REGIONS
########################################
    def _fill_polar_ring( self ):
        """sample_width in degrees"""
        self.sample_width = int( round( self.nphi * 10*self.phi_resolution / 360. ))
        assert( self.sample_width > 1 ) 
        self._find_gap_indices()
        self._set_left_and_right_edge_indices()
        self._iterate_over_masked_regions()

    def _find_gap_indices(self):
        mask = self.polar_ring_mask.astype(bool)
        mask_rolled_right = np.roll( mask,1)
        mask_rolled_left = np.roll( mask,-1)
        
        is_start_of_gap = (mask ^ mask_rolled_left ) & mask
        is_end_of_gap = (mask ^ mask_rolled_right ) & mask
        
        self.gap_start_indices = np.where(is_start_of_gap)[0]
        self.gap_end_indices = np.where( is_end_of_gap)[0]
        
    def _set_left_and_right_edge_indices(self):
        if self.polar_ring_mask[0] == 0:
            self.gap_index_pairs = zip( self.gap_start_indices,
                                    np.roll(self.gap_end_indices,-1) )
        else:
            self.gap_index_pairs = zip( self.gap_start_indices,
                                      self.gap_end_indices )

    def _iterate_over_masked_regions(self):
        for self.iStart, self.iEnd in self.gap_index_pairs:
            self._set_gap_size_and_ranges()
            self._get_linear_gap_interpolator()
            self._get_edge_noise()
            self._fill_in_masked_region_with_Gaussian_noise()
    
    def _set_gap_size_and_ranges(self):
        if self.iEnd < self.iStart:
            self.gap_size = self.iEnd + self.nphi - self.iStart
            self.interpolation_range = np.arange( self.iStart,  self.iEnd + self.nphi )
        else:
            self.gap_size = self.iEnd-self.iStart
            self.interpolation_range = np.arange( self.iStart, self.iEnd)

    def _get_linear_gap_interpolator(self):
#       estimate the edge means
        left_mean = self.polar_ring[self.iStart-self.sample_width:self.iStart].mean()
        right_mean = self.polar_ring[self.iEnd+1:self.sample_width+self.iEnd+1].mean() 

#       find the equation of line connecting edge means
        slope = (right_mean - left_mean) / self.gap_size
        self.line = lambda x : slope* ( x-self.iStart ) + left_mean
    
    def _get_edge_noise(self):
#       estimate the edge noise 
        left_dev = self.polar_ring[self.iStart-self.sample_width:self.iStart].std() 
        right_dev = self.polar_ring[self.iEnd+1:self.sample_width+self.iEnd+1].std() 
        self.edge_noise = (left_dev + right_dev) / 2. #np.sqrt(2)

    def _fill_in_masked_region_with_Gaussian_noise(self):
#       fill in noise about the line
        gap_range = self.interpolation_range % self.nphi
        gap_vals = np.random.normal( self.line(self.interpolation_range), 
                                    self.edge_noise)
        self.polar_ring[gap_range] = gap_vals



class InterpSimple:
    def __init__ ( self,  a,b, qRmax,qRmin, nphi, raw_img_shape, bin_fac=None ) : 
        '''
        Define a polar image with dimensions: (qRmax-qRmin) x nphi
        ==========================================================
        a,b           - float, x_center,y_center of cartesian image that is 
                                being interpolated in pixel units
        
        qRmin,qRmax     - cartesianimage will be interpolated from 
                            qR-qRmin, qR + qRmax in pixel units
        
        nphi          - int, azimuthal dimension of polar image 
                            (number of azimuthal points along polar image)
        
        raw_img_shape - int tuple, ydim, xdim of the raw image 
        
        bin_fac       - float, reduce the size of the cartesian image 
                            by this amount
        '''
        self.a = a      
        self.b = b     
        self.qRmin = qRmin
        self.qRmax = qRmax  
        self.raw_shape = raw_img_shape   
        self.phis_ring     = np.arange( nphi ) * 2 * np.pi / nphi
        self.num_phis_ring = nphi

        self.bin_fac = bin_fac
        
        if bin_fac:
            self.Y,self.X = zoom( np.random.random(raw_img_shape) , 
                                    1. / bin_fac, order=1 ).shape 
        else: 
            self.X = raw_img_shape[1] # fast dimension
            self.Y = raw_img_shape[0] # slow dimension

        
        self.Q  = np.vstack( [ np.ones(self.num_phis_ring)*iq 
                            for iq in np.arange( self.qRmin,self.qRmax ) ] )
        self.PHI = np.vstack( [ self.phis_ring 
                            for iq in np.arange( self.qRmin,  self.qRmax ) ] )
        self.xring = self.Q*np.cos(self.PHI-np.pi) + self.a
        self.yring = self.Q*np.sin(self.PHI-np.pi) + self.b

        self.xring_near = self.xring.astype(int) + \
                            np.round( self.xring - \
                            np.floor(self.xring) ).astype(int)
        self.yring_near = self.yring.astype(int) + \
                            np.round( self.yring - \
                            np.floor(self.yring) ).astype(int)
#       'C' style ordering
        self.indices_1d = self.X* self.yring_near + self.xring_near 

    def nearest( self, data_img , dtype=np.float32):
        '''return a 2d np.array polar image (fastest method)'''
        if self.bin_fac :
            data_img = zoom( data_img, 1. / self.bin_fac, order=1 ) 
        data = data_img.ravel()
        return data[ self.indices_1d ]


