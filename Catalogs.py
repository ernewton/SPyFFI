"""Keep track of Catalogs of objects, usually stars."""
import os.path
import logging

import matplotlib.animation
from astroquery.vizier import Vizier
import zachopy.star
import astropy.coordinates
import astropy.units
import zachopy.utils
import numpy as np

import matplotlib.pylab as plt

import settings
import relations
import Lightcurve
from settings import log_file_handler

logger = logging.getLogger(__name__)
logger.addHandler(log_file_handler)


def makeCatalog(**kwargs):
    """use keywords to select a kind of Catalog,
    enter its parameters and construct it,
    and return the catalog object"""

    # pull out the name of the catalog
    name = kwargs['name']

    # make either a test pattern, or a real star catalog, or something else?
    if name.lower() == 'testpattern':
        # make a gridded test pattern of stars, with keywords passed
        cat = TestPattern(**kwargs)
    elif name.lower() == 'ucac4':
        # make a catalog from UCAC4, with keywords passed
        cat = UCAC4(**kwargs)
    else:
        # interpret the name as a single star, and draw a catalog around it
        star = zachopy.star.Star(name)
        kwargs['ra'], kwargs['dec'] = star.icrs.ra.deg, star.icrs.dec.deg
        cat = UCAC4(**kwargs)
    return cat


class Star(object):
    """a Star object, containing at least RA + Dec + magnitude"""

    def __init__(self, ra=0.0, dec=0.0, tmag=10.0, **kwargs):
        """initialize a star, with a coordinate, magnitude, (and more?)"""

        # the coordinate object stores the ICRS
        self.coord = astropy.coordinates.ICRS(ra=ra, dec=dec,
                                              unit=(astropy.units.deg, astropy.units.deg))
        self.ra = ra
        self.dec = dec
        self.tmag = tmag
        for k in kwargs.keys():
            self.__dict__[k] = kwargs[k]

# note cluster class now needs self.member, identifying cluster members
class Catalog():
	"""an object to keep track of lots of stars"""
	def __init__(self, cluster=None):
		# decide whether or not this Catalog is chatty
		self.directory = 'catalogs/'
		zachopy.utils.mkdir(os.path.join(settings.intermediates, self.directory))
		self.cluster = cluster

	def addLCs(self, fainteststarwithlc=None, fractionofstarswithlc=1.0, seed=None, **kw):
		"""
		addLCs() populates a catalog with light curves.
		
		addLCs() makes use of these keywords:
		fainteststarwithlc=None (what's the faintest magnitude star that should be populated with a lightcurve?)
		fractionofstarswithlc=1.0 (what fraction of eligible stars should be populated with lightcurves, from 0 to 1)
		seed=None (if you want the exact light curves on multiple calls, set a value for the seed)
		
		addLCs() passes additional keywords to SPyFFI.Lightcurve.random(**kw):
		random() makes use of these keyword arguments:
			options=['trapezoid', 'sin'] (a list of the kinds of a variability to choose from)
			fractionwithextremelc=False (should we allow fractionwithextremelc variability [good for movies] or no?)

		"""
		np.random.seed(seed)
		# total number of stars we need to deal with
		ntotal = len(self.tmag)
		
		# make sure everything is at least populated as a constant
		constant = Lightcurve.constant()
		self.lightcurves = np.array([constant] * ntotal)
		
		# make sure that the maximum magnitude for variable stars is defined
		if fainteststarwithlc is None:
			fainteststarwithlc = np.max(self.tmag) + 1
		
		# pull only the stars that pass the brightness cut
		brightenough = (self.tmag <= fainteststarwithlc).nonzero()[0]
		nbrightenough = len(brightenough)
		logger.info(
            '{0} stars are brighter than {1}; '
            'populating {2:.1f}% of them with light curves'.format(
                nbrightenough,
                fainteststarwithlc,
                fractionofstarswithlc * 100))
		
		if self.cluster is None:
			# use the input seed, to ensure it wor
			for i in np.random.choice(brightenough, len(brightenough) * fractionofstarswithlc, replace=False):
				self.lightcurves[i] = Lightcurve.random(**kw)
		else:
			mem, = np.where(self.member == 1)
			nonmem, = np.where(self.member != 1)
			print "assigning periods to members ", len(mem)
			print "assigning periods to nonmembers ", len(nonmem)
			# all members get periods
			for i in mem: 
				self.lightcurves[i] = Lightcurve.random(cluster=self.cluster, **kw)
			# only bright nonmembers get periods
			for i in nonmem:
				if (self.tmag[i] < fainteststarwithlc) or (fainteststarwithlc is None):
					self.lightcurves[i] = Lightcurve.random(**kw)

	@property
	def lightcurvecodes(self):
		"""return an array of the light curve codes"""
		return [lc.code for lc in self.lightcurves]
	
	def arrays(self):
		"""return (static) arrays of positions, magnitudes, and effective temperatures"""
		return self.ra, self.dec, self.tmag, self.temperature
	
	def snapshot(self, bjd=None, epoch=None, exptime=0.5 / 24.0):
		"""return a snapshot of positions, magnitudes, and effective temperatures
		(all of which may be time-varying)"""

		# propagate proper motions
		if bjd is not None:
			epoch = (bjd - 2451544.5) / 365.25 + 2000.0
		else:
			bjd = (epoch - 2000.0) * 365.25 + 2451544.5
		
		ra, dec = self.atEpoch(epoch)
		
		# determine brightness of star
		moment = np.array([lc.integrated(bjd, exptime) for lc in self.lightcurves]).flatten()
		tmag = self.tmag + moment
		
		# determine color of star
		temperature = self.temperature
		assert (ra.shape == tmag.shape)
		return ra, dec, tmag, temperature
		
	def atEpoch(self, epoch):
		
		# how many years since the catalog's epoch?
		timeelapsed = epoch - self.epoch  # in years
		logger.info('projecting catalog {0:.3f} years relative to {1:.0f}'.format(timeelapsed, self.epoch))
		# calculate the dec
		decrate = self.pmdec / 60.0 / 60.0 / 1000.0  # in degrees/year (assuming original was in mas/year)
		decindegrees = self.dec + timeelapsed * decrate
		
		# calculate the unprojected rate of RA motion, using the mean declination between the catalog and present epoch
		rarate = self.pmra / 60.0 / 60.0 / np.cos((
		                                              self.dec + timeelapsed * decrate / 2.0) * np.pi / 180.0) / 1000.0  # in degress of RA/year (assuming original was *projected* mas/year)
		raindegrees = self.ra + timeelapsed * rarate

        # return the current positions
		return raindegrees, decindegrees
	
	def plot(self, epoch=2018.0):
		plt.ion()
		plt.figure('star chart')
		try:
			self.ax.cla()
		except:
			self.ax = plt.subplot()
		ra, dec, tmag, temperature = self.snapshot(epoch=epoch)
		deltamag = 20.0 - tmag
		size = deltamag ** 2 * 5
		try:
			self.plotdata.set_data(ra, dec)
		except:
			self.plotdata = self.ax.scatter(ra, dec, s=size, marker='o', color='grey', alpha=0.3, edgecolors='black')
		# for i in range(len(ra)):
		#  self.ax.text(ra[i], dec[i], '{0:.2f}'.format(tmag[i]),horizontalalignment='center', verticalalignment='center', alpha=0.5, size=8, color='green',weight='bold')
		self.ax.set_aspect(1)
		self.ax.set_xlabel('Right Ascension')
		self.ax.set_ylabel('Declination')
		self.ax.set_title('{0} at epoch {1}'.format(self.__class__.__name__, epoch))
		self.ax.set_xlim(np.min(self.ra), np.max(self.ra))
		self.ax.set_ylim(np.min(self.dec), np.max(self.dec))
		plt.draw()
	
	def movie(self, epochs=[1950, 2050], bitrate=10000):
		metadata = dict(artist='Zach Berta-Thompson (zkbt@mit.edu)')
		self.writer = matplotlib.animation.FFMpegWriter(fps=30, metadata=metadata, bitrate=bitrate)
		
		self.plot(np.min(epochs))
		f = plt.gcf()
		filename = settings.dirs['plots'] + 'testcatalogpropermotions.mp4'
		with self.writer.saving(f, filename, 100):
			for e in np.linspace(epochs[0], epochs[1], 20):
				logger.info('{0}'.format(e))
				self.plot(e)
				self.writer.grab_frame()
		logger.info('saved movie to {0}'.format(filename))
	
	def writeProjected(self, ccd=None, outfile='catalog.txt'):
		# take a snapshot projection of the catalog
		ccd.camera.cartographer.ccd = ccd
		ras, decs, tmag, temperatures = self.snapshot(ccd.camera.bjd,
                                                      exptime=ccd.camera.cadence / 60.0 / 60.0 / 24.0)

		# calculate the CCD coordinates of these stars
		stars = ccd.camera.cartographer.point(ras, decs, 'celestial')
		x, y = stars.ccdxy.tuple

		basemag = self.tmag
		lc = self.lightcurvecodes

		# does the temperature matter at all? (does the PSF have multiple temperatures available?)
		if len(ccd.camera.psf.binned_axes['stellartemp']) > 1:
			data = [ras, decs, self.pmra, self.pmdec, x, y, basemag, temperatures, lc]
			names = ['ra', 'dec', 'pmracosdec_mas', 'pmdec_mas', 'x', 'y', 'tmag', 'stellaratemperature', 'lc']
		else:
			data = [ras, decs, self.pmra, self.pmdec, x, y, basemag, lc]
			names = ['ra', 'dec', 'pmracosdec_mas', 'pmdec_mas', 'x', 'y', 'tmag', 'lc']

		t = astropy.table.Table(data=data, names=names)
		t.write(outfile, format='ascii.fixed_width', delimiter=' ')
		logger.info("save projected star catalog {0}".format(outfile))


class TestPattern(Catalog):
    """a test pattern catalog, creating a grid of stars to fill an image"""

    def __init__(self, lckw=None, starsarevariable=True, **kwargs):
        """create a size x size square (in arcsecs) test pattern of stars,
    with spacing (in arcsecs) between each element and
    magnitudes spanning the range of magnitudes"""
        Catalog.__init__(self)
        self.load(**kwargs)

        if starsarevariable:
            self.addLCs(**lckw)
        else:
            self.addLCs(fractionofstarswithlc=0.0)

    def load(self,
             size=3000.0,  # the overall size of the grid
             spacing=200.0,  # how far apart are stars from each other (")
             magnitudes=[6, 16],  # list of min, max magnitudes
             ra=0.0, dec=0.0,  # made-up center of pattern
             randomizenudgesby=21.1,  # how far to nudge stars (")
             randomizepropermotionsby=0.0,  # random prop. mot. (mas/yr)
             randomizemagnitudes=False,  # randomize the magnitudes?
             **kwargs):

        # set the name of the catalog
        self.name = 'testpattern_{0:.0f}to{1:.0f}'.format(np.min(magnitudes), np.max(magnitudes))

        # how many stars do we need?
        pixels = np.maximum(np.int(size / spacing), 1)
        n = pixels ** 2

        # construct a linear grid of magnitudes
        self.tmag = np.linspace(np.min(magnitudes), np.max(magnitudes), n)[::-1]

        # create a rigid grid of RA and Dec, centered at 0
        ras, decs = np.meshgrid(np.arange(pixels) * spacing, np.arange(pixels) * spacing)

        # offset these (not, make small angle approximations which will fail!)
        self.dec = ((decs - np.mean(decs)) / 3600.0 + dec).flatten()
        self.ra = (ras - np.mean(ras)).flatten() / np.cos(self.dec * np.pi / 180.0) / 3600.0 + ra

        # randomly nudge all of the stars (to prevent hitting same parts of pixels)
        if randomizenudgesby > 0:
            offset = randomizenudgesby * (np.random.rand(2, n) - 0.5) / 3600.0
            self.dec += offset[0, :]
            self.ra += offset[1, :] * np.cos(self.dec * np.pi / 180.0)

        # draw the magnitudes of the stars totally randomly
        if randomizemagnitudes:
            self.tmag = np.random.uniform(np.min(magnitudes), np.max(magnitudes), n)

        # make up some imaginary proper motions
        if randomizepropermotionsby > 0:
            self.pmra = np.random.normal(0, randomizepropermotionsby, n)
            self.pmdec = np.random.normal(0, randomizepropermotionsby, n)
        else:
            self.pmra, self.pmdec = np.zeros(n), np.zeros(n)
        self.epoch = 2018.0
        self.temperature = 5800.0 + np.zeros_like(self.ra)


class UCAC4(Catalog):
    def __init__(self, ra=0.0, dec=90.0,
                 radius=0.2,
                 write=True,
                 fast=False,
                 lckw=None, starsarevariable=True, faintlimit=None, **kwargs):

        # initialize this catalog
        Catalog.__init__(self)
        if fast:
            radius *= 0.1
        self.load(ra=ra, dec=dec, radius=radius, write=write, faintlimit=faintlimit)

        if starsarevariable:
            self.addLCs(**lckw)
        else:
            self.addLCs(fractionofstarswithlc=0.0)

    def load(self, ra=0.0, dec=90.0, radius=0.2, write=True, faintlimit=None):

        # select the columns that should be downloaded from UCAC
        catalog = 'UCAC4'
        ratag = '_RAJ2000'
        dectag = '_DEJ2000'
        if catalog == 'UCAC4':
            vcat = 'I/322A/out'
            rmagtag = 'f.mag'
            jmagtag = 'Jmag'
            vmagtag = 'Vmag'
            pmratag, pmdectag = 'pmRA', 'pmDE'
            columns = ['_RAJ2000', '_DECJ2000', 'pmRA', 'pmDE', 'f.mag', 'Jmag', 'Vmag', 'UCAC4']

        # create a query through Vizier
        v = Vizier(catalog=vcat, columns=columns)
        v.ROW_LIMIT = -1

        # either reload an existing catalog file or download to create a new one
        starsfilename = settings.intermediates + self.directory
        starsfilename += "{catalog}ra{ra:.4f}dec{dec:.4f}rad{radius:.4f}".format(
            catalog=catalog,
            ra=ra,
            dec=dec,
            radius=radius) + '.npy'

        try:
            # try to load a raw catalog file
            logger.info("loading a catalog of stars from {0}".format(starsfilename))
            t = np.load(starsfilename)
        except IOError:
            logger.info('could not load stars')
            # otherwise, make a new query
            logger.info("querying {catalog} "
                        "for ra = {ra}, dec = {dec}, radius = {radius}".format(
                catalog=catalog, ra=ra, dec=dec, radius=radius))
            # load via astroquery
            t = v.query_region(astropy.coordinates.ICRS(ra=ra, dec=dec,
                                                        unit=(astropy.units.deg, astropy.units.deg)),
                               radius='{:f}d'.format(radius), verbose=True)[0]

            # save the queried table
            np.save(starsfilename, t)

        # define the table
        self.table = astropy.table.Table(t)

        ras = np.array(t[:][ratag])
        decs = np.array(t[:][dectag])
        pmra = np.array(t[:][pmratag])
        pmdec = np.array(t[:][pmdectag])
        rmag = np.array(t[:][rmagtag])
        jmag = np.array(t[:][jmagtag])
        vmag = np.array(t[:][vmagtag])

        rbad = (np.isfinite(rmag) == False) * (np.isfinite(vmag))
        rmag[rbad] = vmag[rbad]
        rbad = (np.isfinite(rmag) == False) * (np.isfinite(jmag))
        rmag[rbad] = jmag[rbad]

        jbad = (np.isfinite(jmag) == False) * (np.isfinite(vmag))
        jmag[jbad] = vmag[jbad]
        jbad = (np.isfinite(jmag) == False) * (np.isfinite(rmag))
        jmag[jbad] = rmag[jbad]

        vbad = (np.isfinite(vmag) == False) * (np.isfinite(rmag))
        vmag[vbad] = rmag[vbad]
        vbad = (np.isfinite(vmag) == False) * (np.isfinite(jmag))
        vmag[vbad] = jmag[vbad]

        temperatures = relations.pickles(rmag - jmag)
        imag = rmag - relations.davenport(rmag - jmag)

        pmra[np.isfinite(pmra) == False] = 0.0
        pmdec[np.isfinite(pmdec) == False] = 0.0

        ok = np.isfinite(imag)
        if faintlimit is not None:
            ok *= imag <= faintlimit

        logger.info("found {0} stars with {1} < V < {2}".format(np.sum(ok), np.min(rmag[ok]), np.max(rmag[ok])))
        self.ra = ras[ok]
        self.dec = decs[ok]
        self.pmra = pmra[ok]
        self.pmdec = pmdec[ok]
        self.tmag = imag[ok]
        self.temperature = temperatures[ok]
        self.epoch = 2000.0


class TIC(Catalog):
    
    def __init__(self, ra=300.0, dec=50.0,
                 radius=0.2,
                 write=True,
                 fast=False,
                 lckw=None, starsarevariable=True, faintlimit=None, **kwargs):
        
        # initialize this catalog
        Catalog.__init__(self)
        if fast:
            radius *= 0.1
        self.load(ra=ra, dec=dec, radius=radius, write=write, faintlimit=faintlimit)
        
        if starsarevariable:
            self.addLCs(**lckw)
        else:
            self.addLCs(fractionofstarswithlc=0.0)

    def load(self, ra=300.0, dec=50.0, radius=0.2, write=True, faintlimit=None):
        
        # select the columns that are not in TIC
        catalog  = 'TIC2'
        startag  = "ID"
        ratag    = 'RA'
        dectag   = 'DEC'
        pmratag  = 'PMRA'
        pmdectag = 'PMDEC'
        tmagtag  = "TMAG"
        temptag  = "TEFF"
        typetag  = "OBJTYPE"
        
        ROW_LIMIT = -1
        
        columns = [ratag,dectag,pmratag,pmdectag,tmagtag,temptag,typetag]
        
        # either reload an existing catalog file or download to create a new one
        starsfilename = settings.intermediates + self.directory
        starsfilename +=  "{catalog}ra{ra:.4f}dec{dec:.4f}rad{radius:.4f}".format(
                                                                                  catalog=catalog,
                                                                                  ra=ra,
                                                                                  dec=dec,
                                                                                  radius=radius) + '.npy'


        try:
            # try to load a raw catalog file
            logger.info("loading a catalog of stars from {0}".format(starsfilename))
            t = np.load(starsfilename)
        except IOError:
            logger.info('could not load stars')
            # otherwise, make a new query
            logger.info("querying {catalog} "
                       "for ra = {ra}, dec = {dec}, radius = {radius}".format(
                                                                              catalog=catalog, ra=ra, dec=dec, radius=radius))
            # load via astroquery
            #*****
            t = self.query(ra,dec,radius,columns,ROW_LIMIT)
          
            # save the queried table
            np.save(starsfilename, t)

        # define the table
        self.table = astropy.table.Table(t)

    
        ras = np.array(t[:][ratag])
        decs = np.array(t[:][dectag])
        pmra = np.array(t[:][pmratag])
        pmdec = np.array(t[:][pmdectag])
        tmag = np.array(t[:][tmagtag])
        TEFF = np.array(t[:][temptag])
        Type = np.array(t[:][typetag])

        pmra[np.isfinite(pmra) == False] = 0.0
        pmdec[np.isfinite(pmdec) == False] = 0.0
        
        ok = np.isfinite(tmag)
        if faintlimit is not None:
            ok *= tmag <= faintlimit
        
        self.speak("found {0} stars with {1} < Tmag < {2}".format(np.sum(ok), np.min(tmag[ok]), np.max(tmag[ok])))
        self.ra = ras[ok]
        self.dec = decs[ok]
        self.pmra = pmra[ok]
        self.pmdec = pmdec[ok]
        self.tmag = tmag[ok]
        self.temperature = TEFF[ok]
        self.epoch = 2000.0

    def query(self,ra,dec,radius,column,ROW_LIMIT):
        
        # a more robust tic db storage method?
        TIC_Path = settings.inputs+"TIC_db.db"
        table_name = "Data"
        c,conn = dbm.access_db(TIC_Path)
        
        
        #figure out how to query by radius and box.
        
        # sqlite radius requires sqlite3_create_function. Will look into that.
        # but now seems ok
        # Query by box size
        
        condition = (ra+radius, ra-radius, dec+radius, dec-radius)
        cmd = """SELECT RA,DEC,PMRA,PMDEC,TMAG,TEFF,OBJTYPE
            FROM Data
            WHERE RA < ? AND RA > ? AND DEC < ? AND DEC > ?
            """
        
        c.execute(cmd,condition)
        result = c.fetchall()
        
        if ROW_LIMIT == None or ROW_LIMIT == -1:
            pass
        else:
            result = result[:ROW_LIMIT]
        
        return np.array(result, dtype=[(column[0], float), (column[1], float), (column[2], float),
                                       (column[3], float), (column[4], float), (column[5], float),
                                       (column[6], '|S16')])



class TOCS(Catalog):
    
    def __init__(self, cluster='NGC2516',
    			 ra=119.417, dec=-61.725,
                 radius=1,
                 write=True,
                 fast=False,
                 lckw=None, starsarevariable=True, faintlimit=None, **kwargs):
        
        # initialize this catalog
        Catalog.__init__(self, cluster=cluster)
        
        if fast:
            radius *= 0.1
            
        # catalog name
        if cluster.lower() == 'ngc2516':
        	starsfilename = '/Users/enewton/WORK_DIR/TOCS/Tables/ngc2516master_table_eclip.sb'
        
        self.load(starsfilename, ra=ra, dec=dec, radius=radius, write=write, faintlimit=faintlimit)
        
        if starsarevariable:
            self.addLCs(**lckw)
        else:
            self.addLCs(fractionofstarswithlc=0.0)


    def readtable(self):
        t = astropy.table.Table.read('/Users/enewton/WORK_DIR/TOCS/Tables/ngc2516master_table_eclip.sb', format='ascii.fixed_width_two_line', delimiter='\t')
        return t
        
    def tagnames(self):
		
		startag  = "id"
		ratag    = 'ra'
		dectag   = 'dec'
		pmratag  = 'None'
		pmdectag = 'None'
		tmagtag  = 'None'
		temptag  = 'None'
		typetag  = "f4"
		return startag, ratag, dectag, pmratag, pmdectag, tmagtag, temptag, typetag

	###
	# these are place holders until the TIC comes through...
	###
		        
    def conv2tmag(self, t):
    
    	return np.array(t[:]['v'])
    	
    def conv2teff(self, t):
    
		X = np.array(t[:]['bv']) ## B-V color
		feh = 0.0

		#http://www.aanda.org/articles/aa/full_html/2010/04/aa13204-09/table4.html
		a0 = 0.5665
		a1 = 0.4809
		a2 = -0.0060
		a3 = -0.0613
		a4 = -0.0042
		a5 = -0.0055
		teff = 5040./(a0 + a1*X + a2*X**2 + a3*X*feh + a4*feh + a5*feh**2)
		teff[X<0.18] = 7720
		teff[X>1.29] = 4200
		return teff
      	
      	# M dwarfs:
      	#http://mnras.oxfordjournals.org/content/389/2/585/T3.expansion.html
 
 	###
 	# end place holders
 	###
 	
 	     	
    def load(self, starsfilename, ra=119.0, dec=-61.0, radius=0.2, write=True, faintlimit=None):
        
        # select the columns that are not in TIC
        startag, ratag, dectag, pmratag, pmdectag, tmagtag, temptag, typetag = self.tagnames()
        
                
        # either reload an existing catalog file or download to create a new one
        try:
            # try to load a raw catalog file
            logger.info("loading a catalog of stars from {0}".format(starsfilename))
            t = self.readtable()
        except IOError:
			logger.info('could not load stars')
			# otherwise, make a new query
			logger.info("ELLIE hasn't added an exception handler.")

    
        ras = np.array(t[:][ratag])
        decs = np.array(t[:][dectag])
        if pmratag is not 'None':
        	pmra = np.array(t[:][pmratag])
        else:
        	pmra = np.zeros(len(t))
        	
        if pmratag is not 'None':
        	pmdec = np.array(t[:][pmdectag])
        else:
        	pmdec = np.zeros(len(t))
        
        if tmagtag is not 'None':
        	tmag = np.array(t[:][tmagtag])
        else:
        	tmag = self.conv2tmag(t)
        
        if temptag is not 'None':
       		teff = np.array(t[:][temptag])
       	else:
       		teff = self.conv2teff(t)
       		
        if typetag is not 'None':
        	type = np.array(t[:][typetag])
        else:
        	type = np.zeros(len(t))

        pmra[np.isfinite(pmra) == False] = 0.0
        pmdec[np.isfinite(pmdec) == False] = 0.0
        
        ok = np.isfinite(tmag)
        if faintlimit is not None:
            ok *= tmag <= faintlimit
            
        logger.info(str(len(teff)))
        
        logger.info("found {0} stars with {1} < Tmag < {2}".format(np.sum(ok), np.min(tmag[ok]), np.max(tmag[ok])))
        self.ra = ras[ok]
        self.dec = decs[ok]
        self.pmra = pmra[ok]
        self.pmdec = pmdec[ok]
        self.tmag = tmag[ok]
        self.temperature = teff[ok]
        self.epoch = 2000.0
        self.member = type[ok]




class Trimmed(Catalog):
    """a trimmed catalog, created by removing elements from another catalog"""

    def __init__(self, inputcatalog, keep):
        """inputcatalog = the catalog to start with
    keep = an array indices indicating which elements of inputcatalog to use"""

        Catalog.__init__(self)
        # define the keys to propagate from old catalog to the new one
        keystotransfer = ['ra', 'dec', 'pmra', 'pmdec', 'tmag', 'temperature', 'lightcurves']

        for k in keystotransfer:
            self.__dict__[k] = inputcatalog.__dict__[k][keep]

        self.epoch = inputcatalog.epoch
