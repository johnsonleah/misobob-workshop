import math,os.path,xml.dom.minidom

import matplotlib
import matplotlib.numerix,matplotlib.numerix.ma,matplotlib.colors
import matplotlib.dates
import numpy

import common,xmlstore.xmlstore,xmlstore.util

colormaps = {0:'jet',
             1:'hsv',
             2:'hot',
             3:'cool',
             4:'spring',
             5:'summer',
             6:'autumn',
             7:'winter',
             8:'gray',
             9:'bone',
             10:'copper',
             11:'pink'}

class VariableStore:
    """Abstract base class for objects containing one or more variables that
    can be plotted. It contains functionality for retrieving variable
    short/long names, information on dimensions, and a function that returns
    a hierarchical representation of the variables based on an XML schema.
    """

    def __init__(self):
        pass

    def getVariableNames(self):
        """Returns a list of short names for all variables present in the store.
        """
        return []

    def getVariableLongNames(self):
        """Returns a dictionary with short variable names as keys, long
        variable names as values. This base implementation should be overridden
        by derived classes if it can be done more efficiently.
        """
        return dict([(name,self.getVariable(name).getLongName()) for name in self.getVariableNames()])

    def getVariable(self,varname):
        """Returns a Variable object for the given short variable name.
        """
        return None
        
    def getDimensionInfo(self,dimname):
        """Returns the a dictionary with properties of the specified dimension.
        This includes the label (long name), unit, data type, the preferred axis
        (x or y).
        """
        return {'label':'','unit':'','preferredaxis':None,'datatype':'float'}

    def getVariableTree(self,path,otherstores={}):
        """Returns a tree representation of the variables in the data store,
        represented by an xmlstore.TypedStore object that uses the short names
        of variables as node names.
        
        The data type of each variable node is boolean, which allows the use of
        the returned object as a basis for a tree with checkboxes for each
        variable (e.g. for selecting variables to include in GOTM-GUI reports).
        
        All variables that are present in the store but not represented by a node
        in the store schema will be added to the node named "other" in the tree,
        if that node is present. Nodes that are present in the schema, but whose
        names does not match the name of a variable, while they also do not contain
        any valid variables will be removed from the tree. The label (= long name)
        of nodes representing a variable will set to the long name of the variable
        as it is known in the variable store if it was not yet set.
        """
        # Get the schema as XML DOM object.
        xmlschema = xml.dom.minidom.parse(path)
        
        # Get dictionary linking variable short names to variable long names.
        # it will be used to check whether a node name matches a variable name,
        # and if so also to fill in the node label with the variable long name.
        vardict = self.getVariableLongNames()
        
        # Prune the tree and fill in node labels where needed.
        found = VariableStore.filterNodes(xmlschema.documentElement,vardict)
        
        # Get a list of variables (short names) that were not present in the schema.
        # We will add these to the schema node "other", if that is present.
        remaining = set(vardict.keys()) - found
        
        # Find the "other" node.
        for other in xmlschema.getElementsByTagName('element'):
            if other.getAttribute('name')=='other': break
        else:
            other = None

        # If the "other" node is present, add the remaining variable if there
        # are any; if there are none, remove the "other" node form the tree.
        if other!=None:
            if len(remaining)==0:
                other.parentNode.removeChild(other)
            else:
                # Sort remaining variables alphabetically on their long names
                for varid in sorted(remaining,cmp=lambda x,y: cmp(vardict[x].lower(), vardict[y].lower())):
                    el = xmlschema.createElement('element')
                    el.setAttribute('name',varid)
                    el.setAttribute('label',vardict[varid])
                    el.setAttribute('type','bool')
                    other.appendChild(el)
                    
        # The XML schema has been pruned and overriden where needed.
        # Return an TypedStore based on it.
        return xmlstore.xmlstore.TypedStore(xmlschema,otherstores=otherstores)

    @staticmethod
    def filterNodes(node,vardict):
        """Takes a node in the schema, and checks whether it and its children
        are present in the supplied dictionary. Nodes not present in the
        dictionary are removed unless they have children that are present in
        the dictionary. This function returns a list of dictionary keys that
        we found in/below the node.
        
        This function is called recursively, and will be used internally only
        by getVariableTree.
        """
        nodeids = set()

        # Get the name of the node.
        nodeid = node.getAttribute('name')
        assert nodeid!='', 'Node lacks "name" attribute.'
        
        # If the name of the node matches a key in the dictionary,
        # fill in its label and data type, and add it to the result.
        if nodeid in vardict:
            if not node.hasAttribute('label'):
                node.setAttribute('label',vardict[nodeid])
            node.setAttribute('type','bool')
            nodeids.add(nodeid)
            
        # Test child nodes and append their results as well.
        for ch in xmlstore.util.findDescendantNodes(node,['element']):
            nodeids |= VariableStore.filterNodes(ch,vardict)
            
        # If the current node and its children did not match a key in the
        # dictionary, remove the current node.
        if len(nodeids)==0 and nodeid!='other':
            node.parentNode.removeChild(node)

        # Return a list of dictionary keys that matched.
        return nodeids

class Variable:
    """Abstract class that represents a variable that can be plotted.
    """
    
    class Slice:
        """Object representing a slice of data. It stores the names of
        coordinate dimensions internally, and is also maintains two versions
        of coordinates: one for grid centers and one for grid interfaces.
        
        Currently it can also contain upper and lower confidence boundaries
        for the data values. These objects have the same dimension as the data
        array. Note that this functionality may be relocated in the future.
        """
        def __init__(self,dimensions=()):
            self.dimensions = dimensions
            self.ndim = len(dimensions)
            self.data = None
            self.coords = self.ndim*[None]
            self.coords_stag = self.ndim*[None]
            
            # Bounds for confidence interval (optional)
            self.lbound = None
            self.ubound = None
        
        def isValid(self):
            """Returns true if the slice if valid, i.e., if dimensions and
            coordinates are properly specified. Note that if a slice is valid,
            it might still be empty.
            """
            return (self.ndim>0) and (self.data!=None) and (None not in self.coords) and (None not in self.coords_stag)

        def generateStaggered(self):
            """Creates a vector of interface coordinates from the vector of center
            coordinates, for the specified slice dimension.
            """
            for idim in range(self.ndim):
                assert self.coords[idim]!=None, 'Cannot generate staggered coordinates because centered coordinates have not been set.'
                assert self.coords[idim].ndim==1, 'Currently a staggered grid can only be generated automatically for 1D coordinate vectors.'
                self.coords_stag[idim] = common.getCenters(self.coords[idim],addends=True)
                
        def squeeze(self):
            """Returns the slice with singleton dimensions removed. The singeton
            dimensions are stored as an array of fixed coordinates (with tuples dimension name,
            coordinate value) in the new slice.
            """
            # Find non-singleton dimensions, and store them as fixed extra coordinates.
            gooddimindices = []
            gooddimnames = []
            fixedcoords = []
            for idim,dimname in enumerate(self.dimensions):
                if self.data.shape[idim]>1:
                    # Normal dimension (more than one coordinate)
                    gooddimindices.append(idim)
                    gooddimnames.append(dimname)
                elif self.data.shape[idim]==1:
                    # Singleton dimension
                    fixedcoords.append((dimname,self.coords[idim][0]))

            newslice = Variable.Slice(gooddimnames)
            newslice.coords      = [self.coords     [i].squeeze() for i in gooddimindices]
            newslice.coords_stag = [self.coords_stag[i].squeeze() for i in gooddimindices]
            newslice.data = self.data.squeeze()
            newslice.fixedcoords =fixedcoords

            # Update confidence interval (if any)
            if self.lbound!=None: newslice.lbound = self.lbound.squeeze()
            if self.ubound!=None: newslice.ubound = self.ubound.squeeze()

            return newslice

    def __init__(self,store):
        self.store = store

    def getName(self):
        """Returns the short name (or identifier) of the variable.
        This name must be unique within the data store, as it is the key
        that will be used to retrieve data.
        """
        return ''

    def getLongName(self):
        """Returns a long (pretty) name for the variable.
        """
        return ''

    def getUnit(self):
        """Returns the unit of the variable.
        """
        return ''

    def getDimensions(self):
        """Returns the names of the dimensions of the variable as tuple of strings.
        """
        return ()

    def getSlice(self,bounds):
        """Returns a slice from the data. The bounds argument must be a
        list of n tuples, with n being the number of dimensions of the variable
        (as returned by getDimensions). Each tuple must contain a lower- and upper
        boundary of the corresponding dimension. These bounds may be used to
        retrieve a subset of data more efficiently - the Variable is *not*
        required to return only data from within the specified range!
        """
        return self.Slice()

    def getDimensionInfo(self,dimname):
        """Gets information on the specified dimension of the variable.
        See also VariabelStore.getDimensionInfo.
        """
        return self.store.getDimensionInfo(dimname)

        
class MergedVariableStore(VariableStore):
    """Class that merges multiple data sources (VariableStore objects) with
    the same variables, thus creating a new dimension corresponding to the
    index of the original data source.
    """
    
    class MergedVariable(Variable):
        def __init__(self,store,variables,mergedimid):
            Variable.__init__(self,store)
            self.vars = variables
            self.mergedimid = mergedimid

        def getName(self):
            return self.vars[0].getName()

        def getLongName(self):
            return self.vars[0].getLongName()

        def getUnit(self):
            return self.vars[0].getUnit()

        def getDimensions(self):
            return tuple([self.mergedimid]+list(self.vars[0].getDimensions()))

        def getSlice(self,bounds):
            slice = self.Slice(self.getDimensions())
            assert len(bounds)==slice.ndim, 'Number of specified dimensions (%i) does not equal number of data dimensions (%i).' % (len(bounds),slice.ndim)
            
            # Get bound indices for the merged dimension
            ifirst,ilast = 0,len(self.vars)-1
            if bounds[0][0]!=None and bounds[0][0]>ifirst: ifirst = int(math.floor(bounds[0][0]))
            if bounds[0][1]!=None and bounds[0][1]<ilast : ilast  = int(math.ceil (bounds[0][1]))
            slice.coords[0] = numpy.linspace(float(ifirst),float(ilast),ilast-ifirst+1)
            slice.coords_stag[0] = common.getCenters(slice.coords[0],addends=True)

            first = True
            for ivar,var in enumerate(self.vars[ifirst:ilast+1]):
                curslice = var.getSlice(bounds[1:])
                if first:
                    slice.coords[1:] = curslice.coords
                    slice.coords_stag[1:] = curslice.coords_stag
                    slice.data = matplotlib.numerix.empty(tuple([ilast-ifirst+1]+list(curslice.data.shape)),matplotlib.numerix.typecode(curslice.data))
                    first = False
                slice.data[ivar,...] = curslice.data
            return slice

    def __init__(self,stores,mergedimid='obs',mergedimname='observation'):
        VariableStore.__init__(self)
        self.stores = stores
        self.mergedimid = mergedimid
        self.mergedimname = mergedimname

    def getVariableNames(self):
        return self.stores[0].getVariableNames()

    def getVariableLongNames(self):
        return self.stores[0].getVariableLongNames()

    def getDimensionInfo(self,dimname):
        if dimname==self.mergedimid: 
            info = VariableStore.getDimensionInfo(self,dimname)
            info['label'] = self.mergedimname
            return info
        return self.stores[0].getDimensionInfo(dimname)

    def getVariable(self,varname):
        vars = []
        for store in self.stores:
            var = store.getVariable(varname)
            if var==None:
                print 'Store "%s" does not contain variable "%s".' % (store,varname)
                return None
            vars.append(var)
        return MergedVariableStore.MergedVariable(self,vars,self.mergedimid)

class CustomVariableStore(VariableStore):
    """A custom VariableStore that starts out empty, and can be populated
    with existing Variable objects (from different existing stores) to
    create a custom variable selection.
    """

    def __init__(self):
        VariableStore.__init__(self)
        self.vars = []
        
    def addVariable(self,var):
        self.vars.append(var)

    def getVariableNames(self):
        return [v.getName() for v in self.vars]

    def getVariableLongNames(self):
        return [v.getLongName() for v in self.vars]

    def getDimensionInfo(self,dimname):
        return VariableStore.getDimensionInfo(self,dimname)

    def getVariable(self,varname):
        for v in self.vars:
            if v.getName()==varname: return v
        return None
        
class CustomDateFormatter(matplotlib.dates.DateFormatter):
    """Extends the matplotlib.dates.DateFormatter class, adding support
    for the first letter of the day name (%e), the first letter of the
    month name (%n) and the quarter numbers Q1, Q2, Q3, Q4 (%Q).
    """
    def __init__(self,pattern):
        matplotlib.dates.DateFormatter.__init__(self,pattern)

    def strftime(self, dt, fmt):
        if ('%e' in fmt):
            dayname = str(matplotlib.dates.DateFormatter.strftime(self,dt,'%A'))
            fmt = fmt.replace('%e',dayname[0])
        if ('%n' in fmt):
            month = str(matplotlib.dates.DateFormatter.strftime(self,dt,'%b'))
            fmt = fmt.replace('%n',month[0])
        if ('%Q' in fmt):
            monthnr = int(matplotlib.dates.DateFormatter.strftime(self,dt,'%m'))
            fmt = fmt.replace('%Q','Q%i' % math.ceil(monthnr/3.))
        return matplotlib.dates.DateFormatter.strftime(self,dt,fmt)
        
class VariableTransform(Variable):
    """Abstract base class for variable transform. By default it inherits
    most properties (unit, dimensions) from the source variable, while the
    original short- and long name are prefixed with a string describing the
    transformation.
    """
    def __init__(self,sourcevar,nameprefix='',longnameprefix='',name=None,longname=None):
        Variable.__init__(self,None)
        assert sourcevar!=None, 'The source variable for a transform cannot be None.'
        self.sourcevar = sourcevar
        if name==None:
            name = nameprefix + self.sourcevar.getName()
        if longname==None: 
            longname = longnameprefix + self.sourcevar.getLongName()
        self.name     = name
        self.longname = longname

    def getName(self):
        """Return short name for the variable.
        """
        return self.name

    def getLongName(self):
        """Return long name for the variable.
        """
        return self.longname

    def getUnit(self):
        """Return variable unit, copied form source variable.
        """
        return self.sourcevar.getUnit()

    def getDimensions(self):
        """Return list of variable dimensions, copied form source variable.
        """
        return self.sourcevar.getDimensions()

    def getDimensionInfo(self,dimname):
        """Return information on specified dimension, copied form source
        variable.
        """
        return self.sourcevar.getDimensionInfo(dimname)

class VariableReduceDimension(VariableTransform):
    """Abstract base class for a variable transform that reduces the number
    of variable dimensions by one (e.g. average, integral, slice).
    """
    def __init__(self,variable,dimension,**kwargs):
        VariableTransform.__init__(self,variable,**kwargs)
        self.dimension = dimension

        # Retrieve the index of the dimension that we want to take out.
        dims = self.sourcevar.getDimensions()
        for (i,d) in enumerate(dims):
            if d==self.dimension: break
        else:
            assert False, 'Dimension "%s" is not present for this variable.' % self.dimension
        self.idimension = i

    def getDimensions(self):
        """Return the variable dimensions, taken from the source variable but
        with one dimension taken out.
        """
        dims = self.sourcevar.getDimensions()
        return [d for d in dims if d!=self.dimension]
        
class VariableSlice(VariableReduceDimension):
    """Transformation that takes a slice through the variable in one dimension.
    """
    def __init__(self,variable,slicedimension,slicecoordinate,**kwargs):
        VariableReduceDimension.__init__(self,variable,slicedimension,**kwargs)
        self.sliceval = slicecoordinate

    def getSlice(self,bounds):
        newslice = self.Slice(self.getDimensions())

        newbounds = list(bounds)
        newbounds.insert(self.idimension,(self.sliceval,self.sliceval))
        sourceslice = self.sourcevar.getSlice(newbounds)
        if not sourceslice.isValid: return newslice

        assert sourceslice.coords[self.idimension].ndim==1, 'Slicing is not (yet) supported for dimensions that have coordinates that depend on other dimensions.'
        ipos = sourceslice.coords[self.idimension].searchsorted(self.sliceval)
        if ipos==0 or ipos>=sourceslice.coords[self.idimension].shape[0]: return newslice
        leftx  = sourceslice.coords[self.idimension][ipos-1]
        rightx = sourceslice.coords[self.idimension][ipos]
        deltax = rightx-leftx
        stepx = self.sliceval-leftx
        relstep = stepx/deltax

        if len(dims)==1:
            data.pop(self.idimension)
            for idat in range(len(data)):
                if data[idat].ndim==2:
                    if ipos>0 and ipos<len(data[self.idimension]):
                        # centered: left and right bound available
                        left  = data[idat].take((ipos-1,),self.idimension).squeeze()
                        right = data[idat].take((ipos,  ),self.idimension).squeeze()
                        data[idat] = left + relstep*(right-left)
                    elif ipos==0:
                        # left-aligned (only right bound available)
                        data[idat]=data[idat].take((ipos,),self.idimension).squeeze()
                    else:
                        # right-aligned (only left bound available)
                        data[idat]=data[idat].take((ipos-1,),self.idimension).squeeze()
        else:
            assert False,'Cannot take slice because the result does not have 1 coordinate dimension (instead it has %i: %s).' % (len(dims),dims)
        return newslice

class VariableAverage(VariableReduceDimension):
    """Transformation that takes the average of the variable across one dimension.
    """
    def __init__(self,variable,dimname,centermeasure=0,boundsmeasure=0,percentilewidth=.5,**kwargs):
        dimlongname = variable.getDimensionInfo(dimname)['label']
        kwargs.setdefault('nameprefix',  'avg_')
        kwargs.setdefault('longnameprefix',dimlongname+'-averaged ')
        VariableReduceDimension.__init__(self,variable,dimname,**kwargs)
        self.centermeasure = centermeasure
        self.boundsmeasure = boundsmeasure
        self.percentilewidth = percentilewidth

    def getSlice(self,bounds):
        newbounds = list(bounds)
        newbounds.insert(self.idimension,(None,None))
        sourceslice = self.sourcevar.getSlice(newbounds)
        if not sourceslice.isValid(): return self.Slice()
        
        slice = self.Slice(self.getDimensions())
        for idim in range(len(sourceslice.coords)):
            if idim==self.idimension: continue
            coords = sourceslice.coords[idim]
            coords_stag = sourceslice.coords_stag[idim]
            if sourceslice.coords[idim].ndim>1:
                coords = coords.take((0,),self.idimension)
                coords_stag = coords_stag.take((0,),self.idimension)
                coords.shape = coords.shape[:self.idimension]+coords.shape[self.idimension+1:]
                coords_stag.shape = coords_stag.shape[:self.idimension]+coords_stag.shape[self.idimension+1:]
            itargetdim = idim
            if idim>self.idimension: itargetdim-=1
            slice.coords[itargetdim] = coords
            slice.coords_stag[itargetdim] = coords_stag
        
        weights = sourceslice.coords_stag[self.idimension]
        if weights.ndim==1:
            weights = common.replicateCoordinates(numpy.diff(weights),sourceslice.data,self.idimension)
        else:
            print weights.shape
            weights = numpy.diff(weights,axis=self.idimension)
            print weights.shape
            print sourceslice.data.shape
        
        # Normalize weights so their sum over the dimension to analyze equals one
        summedweights = weights.sum(axis=self.idimension)
        newshape = list(summedweights.shape)
        newshape.insert(self.idimension,1)
        weights /= summedweights.reshape(newshape).repeat(sourceslice.data.shape[self.idimension],self.idimension)
        
        if self.centermeasure==0 or self.boundsmeasure==0:
            # We need the mean and/or standard deviation. Calculate the mean,
            # which is needed for either measure.
            mean = (sourceslice.data*weights).sum(axis=self.idimension)
        
        if self.centermeasure==1 or self.boundsmeasure==1:
            # We will need percentiles. Sort the data along dimension to analyze,
            # and calculate cumulative (weigth-based) distribution.
            
            # Sort the data along the dimension to analyze, and sort weights
            # in the same order
            sortedindices = sourceslice.data.argsort(axis=self.idimension)
            sorteddata    = common.argtake(sourceslice.data,sortedindices,axis=self.idimension)
            sortedweights = common.argtake(weights,sortedindices,self.idimension)
            
            # Calculate cumulative distribution values along dimension to analyze.
            cumsortedweights = sortedweights.cumsum(axis=self.idimension)
            
            # Calculate coordinates for interfaces between data points, to be used
            # as grid for cumulative distribution
            sorteddata = (numpy.concatenate((sorteddata.take((0,),axis=self.idimension),sorteddata),axis=self.idimension) + numpy.concatenate((sorteddata,sorteddata.take((-1,),axis=self.idimension)),axis=self.idimension))/2.
            cumsortedweights = numpy.concatenate((numpy.zeros(cumsortedweights.take((0,),axis=self.idimension).shape,cumsortedweights.dtype),cumsortedweights),axis=self.idimension)
        
        if self.centermeasure==0:
            # Use mean for center
            slice.data = mean
        elif self.centermeasure==1:
            # Use median for center
            slice.data = common.getPercentile(sorteddata,cumsortedweights,.5,self.idimension)
        else:
            assert False, 'Unknown choice %i for center measure.' % self.centermeasure

        if self.boundsmeasure==0:
            # Standard deviation will be used as bounds.
            var = (sourceslice.data**2*weights).sum(axis=self.idimension) - mean**2
            sd = numpy.sqrt(var)
            slice.lbound = slice.data-sd
            slice.ubound = slice.data+sd
        elif self.boundsmeasure==1:
            # Percentiles will be used as bounds.
            lowcrit = (1.-self.percentilewidth)/2.
            highcrit = 1.-lowcrit
            slice.lbound = common.getPercentile(sorteddata,cumsortedweights, lowcrit,self.idimension)
            slice.ubound = common.getPercentile(sorteddata,cumsortedweights,highcrit,self.idimension)
        else:
            assert False, 'Unknown choice %i for bounds measure.' % self.boundsmeasure
        
        return slice

class VariableFlat(VariableReduceDimension):
    """Transformation that flattens one dimension of the variable, creating
    n duplicate coordinates in all other dimensions, with n being the number
    of coordinates in the flattened dimension.
    """
    def __init__(self,variable,dimname,targetdim,**kwargs):
        dimlongname = variable.getDimensionInfo(dimname)['label']
        kwargs.setdefault('nameprefix',  'flat_')
        kwargs.setdefault('longnameprefix',dimlongname+'-combined ')
        VariableReduceDimension.__init__(self,variable,dimname,**kwargs)
        
        self.targetdim = targetdim
        self.itargetdim = list(self.sourcevar.getDimensions()).index(self.targetdim)
        self.inewtargetdim = self.itargetdim
        if self.idimension<self.itargetdim: self.inewtargetdim -= 1
        
    def getSlice(self,bounds):
        assert len(bounds)==len(self.sourcevar.getDimensions())-1, 'Invalid number of dimension specified.'
        
        newbounds = list(bounds)
        newbounds.insert(self.idimension,(None,None))
        sourceslice = self.sourcevar.getSlice(newbounds)
        newslice = self.Slice(self.getDimensions())
        
        assert sourceslice.coords[self.idimension].ndim==1,'Currently, the dimension to flatten cannot depend on other dimensions.'
        assert sourceslice.coords[self.itargetdim].ndim==1,'Currently, the dimension to absorb flattened values cannot depend on other dimensions.'
        
        # Get length of dimension to flatten, and of dimension to take flattened values.
        sourcecount = sourceslice.coords[self.idimension].shape[0]
        targetcount = sourceslice.coords[self.itargetdim].shape[0]

        # Create new coordinates for dimension that absorbs flattened values.
        newtargetcoords = matplotlib.numerix.empty((targetcount*sourcecount,),matplotlib.numerix.typecode(sourceslice.coords[self.itargetdim]))
        
        # Create a new value array.
        newdatashape = list(sourceslice.data.shape)
        newdatashape[self.itargetdim] *= sourcecount
        del newdatashape[self.idimension]
        newdata = matplotlib.numerix.empty(newdatashape,matplotlib.numerix.typecode(sourceslice.data))
            
        for i in range(0,targetcount):
            newtargetcoords[i*sourcecount:(i+1)*sourcecount] = sourceslice.coords[self.itargetdim][i]
            for j in range(0,sourcecount):
                sourceindices = [slice(0,None,1) for k in range(sourceslice.ndim)]
                sourceindices[self.itargetdim] = slice(i,i+1,1)
                sourceindices[self.idimension] = slice(j,j+1,1)
                targetindices = [slice(0,None,1) for k in range(newdata.ndim)]
                targetindices[self.inewtargetdim] = slice(i*sourcecount+j,i*sourcecount+j+1,1)
                newdata[tuple(targetindices)] = sourceslice.data[tuple(sourceindices)].copy()

        newslice.coords      = [c for i,c in enumerate(sourceslice.coords     ) if i!=self.idimension]
        newslice.coords_stag = [c for i,c in enumerate(sourceslice.coords_stag) if i!=self.idimension]
        newslice.coords[self.inewtargetdim] = newtargetcoords
        newslice.data = newdata
        return newslice

class FigureProperties(xmlstore.xmlstore.TypedStore):
    """Class for figure properties, based on xmlstore.TypedStore.
    
    Currently this does nothing specific except automatically selecting the
    correct XML schema. In the future this class can host convertors that
    convert between different versions of the XML schema for figures.
    """

    def __init__(self,valueroot=None,adddefault = True):
        schemadom = os.path.join(common.getDataRoot(),'schemas/figure/0001.xml')
        xmlstore.xmlstore.TypedStore.__init__(self,schemadom,valueroot,adddefault=adddefault)

    schemadict = None
    @staticmethod
    def getDefaultSchemas():
        if FigureProperties.schemadict==None:
            FigureProperties.schemadict = xmlstore.xmlstore.ShortcutDictionary.fromDirectory(os.path.join(common.getDataRoot(),'schemas/figure'))
        return FigureProperties.schemadict
        
class Figure(xmlstore.util.referencedobject):
    """Class encapsulating a MatPlotLib figure. The data for the figure is
    provided as one or more VariableStore objects, with data series being
    identified by the name of the VariableStore and the name of the variable
    to be plotted. All configuration of the plots is done through a
    xmlstore.TypedStore object.
    """

    def __init__(self,figure=None,size=(10,8),defaultfont=None):
        xmlstore.util.referencedobject.__init__(self)

        # If no MatPlotLib figure is specified, create a new one, assuming
        # we want to export to file.        
        if figure==None:
            figure = matplotlib.figure.Figure(figsize=(size[0]/2.54,size[1]/2.54))
            canvas = matplotlib.backends.backend_agg.FigureCanvasAgg(figure)
        
        # If no default font is specified, use the MatPlotLib default.
        if defaultfont==None:
            defaultfont = matplotlib.font_manager.FontProperties().get_name()
        
        self.figure = figure
        self.canvas = figure.canvas

        # Create store for the explicitly set properties
        self.properties = FigureProperties()
        self.propertiesinterface = self.properties.getInterface()
        self.propertiesinterface.processDefaultChange = -1
        self.propertiesinterface.connect('afterChange',self.onPropertyChanged)
        self.propertiesinterface.connect('afterStoreChange',self.onPropertyStoreChanged)
        
        # Create store for property defaults
        self.defaultproperties = FigureProperties()

        # Set some default properties.
        self.defaultproperties['FontName'       ].setValue(defaultfont)
        self.defaultproperties['FontScaling'    ].setValue(100)
        self.defaultproperties['Grid'           ].setValue(False)
        self.defaultproperties['Legend/Location'].setValue(0)
        self.defaultproperties['HasColorMap'    ].setValue(False)
        self.defaultproperties['ColorMap'       ].setValue(0)
        setLineProperties(self.defaultproperties['Grid/LineProperties'],CanHaveMarker=False,mplsection='grid')

        # Attach the store with figure defaults to the customized store.
        self.properties.setDefaultStore(self.defaultproperties)

        self.sources = {}
        self.defaultsource = None
        self.updating = True
        self.dirty = False
        self.haschanged = False
        
        self.callbacks = {'completeStateChange':[]}
        
    def unlink(self):
        """Cleans up the figure, releasing the embedded TypedStore objects.
        """
        self.properties.disconnectInterface(self.propertiesinterface)
        self.propertiesinterface = None
        
        self.defaultproperties.release()
        self.defaultproperties = None
        self.properties.release()
        self.properties = None
        
    def registerCallback(self,eventname,callback):
        assert eventname in self.callbacks, 'Event "%s" is unknown.' % eventname
        self.callbacks[eventname].append(callback)

    def setUpdating(self,allowupdates):
        """Enables/disables updating of the figure as its properties change.
        """
        oldval = self.updating
        if oldval != allowupdates:
            self.updating = allowupdates
            if allowupdates and self.dirty: self.update()
        return oldval

    def onPropertyChanged(self,node,feature):
        """Called internally after a property in the TypedStore with customized
        figure settings has changed.
        """
        if feature=='value':
            self.onPropertyStoreChanged()

    def onPropertyStoreChanged(self):
        """Called internally after all properties in the TypedStore with
        customized figure settings have changed at once.
        """
        self.haschanged = True
        self.update()

    def clearSources(self):
        """Clears the list of VariableStore data sources currently registered
        with the figure.
        """
        self.sources = {}
        self.defaultsource = None

    def addDataSource(self,name,obj):
        """Adds a VariableStore data source to the figure, using the specified
        name.
        """
        self.sources[name] = obj
        if self.defaultsource==None: self.defaultsource = name

    def clearProperties(self,deleteoptional=True):
        """Clear all customized figure properties (which means defaults will be used).
        If deleteoptional is set to True, optional nodes such as data series will be
        deleted as well, resulting in an empty figure.
        """
        self.properties.root.clearValue(recursive=True,deleteclones=deleteoptional)

    def setProperties(self,props):
        """Specifies a new set of custom figure properties.
        The properties can be specified as path to an XML file, an in-memory
        XML node, among others.
        """
        self.properties.setStore(props)
        self.update()

    def getPropertiesCopy(self):
        """Get a copy of the current figure properties as XML node.
        """
        return self.properties.toXmlDom()

    def clearVariables(self):
        """Clears all data series. Thsi does not automatically clear the
        list of registered data sources (VariableStore objects).
        """
        self.properties['Data'].removeChildren('Series')

    def addVariable(self,varname,source=None,replace=True):
        """Add a variable to the figure. If no data source name if specified,
        the first registered source will be used. The specified variable must
        match the name of a vairbale in the data source to be used.
        """
        datanode = self.properties['Data']
        varpath = '/'+varname
        if source!=None: varpath = source+varpath
        if replace:
            series = datanode.getChildById('Series',varpath,create=True)
            self.defaultproperties['Data'].getChildById('Series',varpath,create=True)
        else:
            series = datanode.addChild('Series',id=varpath)
            self.defaultproperties['Data'].addChild('Series',id=varpath)
        self.update()
        return series

    def hasChanged(self):
        """Returns True if the figure properties have changed since the store
        was created or resetChanged was called.
        """
        return self.haschanged

    def resetChanged(self):
        """Resets the "changed" status of the figure properties.
        """
        self.haschanged = False
        
    def exportToFile(self,path,dpi=150):
        """Export the contents of the figure to file.
        """
        self.canvas.print_figure(str(path),dpi=dpi)
        
    def update(self):
        """Update the figure.
        
        Everything happens here. The current set of customized properties is
        interpreted, data slice are obtained from the data sources, default
        figure properties are set based on properties of the obtained data,
        and the figure is built and shown.
        """
        if not self.updating:
            self.dirty = True
            return
            
        self.figure.clear()

        axes = self.figure.add_subplot(111)
        
        textscaling = self.properties['FontScaling'].getValue(usedefault=True)/100.
        
        # First scale the default font size; this takes care of all relative font sizes (e.g. "small")
        matplotlib.font_manager.fontManager.set_default_size(textscaling*matplotlib.rcParams['font.size'])
        
        # Now get some relevant font sizes.
        # Scale font sizes with text scaling parameter if they are absolute sizes.
        # (if they are strings, they are relative sizes already)
        fontfamily = self.properties['FontName'].getValue(usedefault=True)
        fontsizes = {
            'axes.titlesize' :10,#matplotlib.rcParams['axes.titlesize'],
            'axes.labelsize' :8, #matplotlib.rcParams['axes.labelsize'],
            'xtick.labelsize':8, #matplotlib.rcParams['xtick.labelsize'],
            'ytick.labelsize':8, #matplotlib.rcParams['ytick.labelsize']
            'legend':8
        }
        for k,v in fontsizes.iteritems():
            if not isinstance(v,basestring): fontsizes[k]=v*textscaling
            
        # Line colors to cycle through
        linecolors = ((0,0,255),(0,255,0),(255,0,0),(0,255,255),(255,0,255),(255,255,0),(0,0,0))

        # Get forced axes boundaries (will be None if not set; then we autoscale)
        dim2data = {}
        defaultaxes = self.defaultproperties['Axes']
        forcedaxes = self.properties['Axes']
        for forcedaxis in forcedaxes.getLocationMultiple(['Axis']):
            istimeaxis = forcedaxis['IsTimeAxis'].getValue(usedefault=True)
            logscale = False
            if istimeaxis:
                axmin = forcedaxis['MinimumTime'].getValue()
                axmax = forcedaxis['MaximumTime'].getValue()
                if axmin!=None: axmin = common.date2num(axmin)
                if axmax!=None: axmax = common.date2num(axmax)
            else:
                axmin = forcedaxis['Minimum'].getValue()
                axmax = forcedaxis['Maximum'].getValue()
                logscale = forcedaxis['LogScale'].getValue()
            dim2data[forcedaxis.getSecondaryId()] = {'forcedrange':[axmin,axmax],'logscale':logscale}

        # Shortcuts to the nodes specifying the variables to plot.
        forceddatanode = self.properties['Data']
        forcedseries = forceddatanode.getLocationMultiple(['Series'])

        # Shortcut to the node that will hold defaults for the plotted variables.
        defaultdatanode = self.defaultproperties['Data']
        olddefaults = [node.getSecondaryId() for node in defaultdatanode.getLocationMultiple(['Series'])]

        # This variable will hold all long names of the plotted variables.
        # These will later be joined to create the plot title.
        titles = []
        
        # No colorbar created, and no colormap used (yet).
        cb = None
        hascolormap = False
        
        cm = getattr(matplotlib.cm,colormaps[self.properties['ColorMap'].getValue(usedefault=True)])
        cm.set_bad('w')
        
        # Start with z order index 0 (incrementing it with every item added)
        zorder = 0
        
        # Dictionary holding number of data series per number of independent dimensions.
        plotcount = {1:0,2:0}
        
        # Dictionary with legend information (handles to drawn data series and the series
        # label) to be filled while adding data series.
        legenddata = {'handles':[],'labels':[]}

        for (iseries,seriesnode) in enumerate(forcedseries):
            # Get the path of the data source (data source identifier + variable id)
            varpath = seriesnode.getSecondaryId()
            if varpath=='':
                print 'Skipping data series %i because the secondary node id (i.e., variable source and name) is not set.'
                continue
                
            # Extract variable source name and the variable identifier.
            varsource,varname = varpath.split('/',1)
            if varsource=='':
                # No data source specified; take default.
                assert self.defaultsource!=None, 'No data source set for variable "%s", but no default source available either.' % varname
                varsource = self.defaultsource
                
            # Get variable object.
            varstore = self.sources[varsource]
            var = varstore.getVariable(varname)
            assert var!=None, 'Source "%s" does not contain variable with name "%s".' % (varsource,varname)
            longname = var.getLongName()
            
            # Create default series information
            defaultseriesnode = defaultdatanode.getChildById('Series',varpath,create=True)
            defaultseriesnode['Label'].setValue(longname)
            defaultseriesnode['PlotType3D'].setValue(0)
            defaultseriesnode['HasConfidenceLimits'].setValue(False)
            setLineProperties(defaultseriesnode['LineProperties'])
            defaultseriesnode['ShowEdges'].setValue(False)
            defaultseriesnode['UseColorMap'].setValue(True)
            defaultseriesnode['EdgeColor'].setValue(xmlstore.xmlstore.StoreColor(0,0,0))
            defaultseriesnode['EdgeWidth'].setValue(1.)
            label = seriesnode['Label'].getValue(usedefault=True)
            
            # Old defaults will be removed after all series are plotted.
            # Register that the current variable is active, ensuring its default will remain.
            if varpath in olddefaults: olddefaults.remove(varpath)

            # Store the variable long name (to be used for building title)
            titles.append(label)

            # Build list of dimension boundaries for current variable.
            # For dimensions that have equal lower and upper bound, take a slice.
            dimbounds = []
            originaldims = var.getDimensions()
            for dimname in originaldims:
                if dimname in dim2data:
                    # We have boundaries set on the current dimension.
                    forcedrange = dim2data[dimname].get('forcedrange',(None,None))
                    if forcedrange[0]!=None: forcedrange[0] = forcedrange[0]
                    if forcedrange[1]!=None: forcedrange[1] = forcedrange[1]
                    if forcedrange[0]==forcedrange[1] and forcedrange[0]!=None:
                        # Equal upper and lower boundary: take a slice.
                        var = VariableSlice(var,dimname,forcedrange[0])
                    else:
                        dimbounds.append(forcedrange)
                else:
                    # No boundaries set.
                    dimbounds.append((None,None))
                    
            # Get the data
            varslice = var.getSlice(dimbounds)
            
            # Skip this variable if no data are available.
            if not varslice.isValid(): continue

            # Now we are at the point where getting the data worked.
            # Register all used dimensions (even the "sliced out" ones)
            # as used, and get information on them.
            for dimname in originaldims:
                dimdata = dim2data.setdefault(dimname,{'forcedrange':[None,None]})
                dimdata['used'] = True
                diminfo = var.getDimensionInfo(dimname)
                dimdata.update(diminfo)

            # Add the variable itself to the dimension list.
            dimdata = dim2data.setdefault(varpath,{'forcedrange':(None,None)})
            dimdata.update({'label':var.getLongName(),'unit':var.getUnit(),'datatype':'float','tight':False,'logscale':False})
            
            # Find non-singleton dimensions (singleton dimension: dimension with length one)
            # Store singleton dimensions as fixed extra coordinates.
            varslice = varslice.squeeze()
            
            # Mask infinite/nan values, if any
            invalid = numpy.logical_not(numpy.isfinite(varslice.data))
            if invalid.any():
                print 'WARNING: masking %i invalid values (inf or nan) out of %i.' % (invalid.sum(),invalid.size)
                varslice.data = matplotlib.numerix.ma.array(varslice.data,mask=invalid)

            defaultseriesnode['DimensionCount'].setValue(varslice.ndim)

            # Get the plot type for 3D plots.
            plottype3d = seriesnode['PlotType3D'].getValue(usedefault=True)

            # We use a staggered grid (coordinates at interfaces,
            # values at centers) for certain 3D plot types.
            staggered = (varslice.ndim==2 and plottype3d==0)
            
            # Create shortcut to applicable coordinate set.
            if staggered:
                coords = varslice.coords_stag
            else:
                coords = varslice.coords

            # Get the minimum and maximum values; store these as default.
            dim2data[varpath]['datarange'] = [varslice.data.min(),varslice.data.max()]

            # Enumerate over the dimension of the variable.
            for idim,dimname in enumerate(varslice.dimensions):
                # Get minimum and maximum coordinates.
                if coords[idim].ndim==1:
                    # Coordinates provided as vector (1D) valid over whole domain.
                    datamin = coords[idim][0]
                    datamax = coords[idim][-1]
                else:
                    # Coordinates are provided as multidimensional array, with a value for every
                    # coordinate (data point) in the domain. We assume that for a given point
                    # in the space of the other coordinates, the current cordinate increases
                    # monotonously (i.e., position 0 holds the lowest value and position -1 the
                    # highest)
                    datamin = coords[idim].take((0, ),idim).min()
                    datamax = coords[idim].take((-1,),idim).max()

                # Update effective dimension bounds                    
                effrange = dim2data[dimname].setdefault('datarange',[None,None])
                if effrange[0]==None or datamin<effrange[0]: effrange[0] = datamin
                if effrange[1]==None or datamax>effrange[1]: effrange[1] = datamax
            
            # Plot the data series
            if varslice.ndim==0:
                # Zero-dimensional coordinate space (i.e., only a single data value is available)
                # No plotting of coordinate-less data (yet)
                pass
            if varslice.ndim==1:
                # One-dimensional coordinate space (x). Use x-axis for coordinates, unless the
                # dimension information states it is preferably uses the y-axis.
                X,Y = varslice.coords[0], varslice.data
                xname,yname = varslice.dimensions[0], varpath
                switchaxes = (dim2data[varslice.dimensions[0]]['preferredaxis']=='y')
                if switchaxes:
                    X,Y = Y,X
                    xname,yname = yname,xname
                
                # Get data series style settings
                defaultseriesnode['LineProperties/Color'].setValue(xmlstore.xmlstore.StoreColor(*linecolors[plotcount[1]%len(linecolors)]))
                plotargs = getLineProperties(seriesnode['LineProperties'])
                
                # plot confidence interval (if any)
                hasconfidencelimits = (varslice.ubound!=None or varslice.lbound!=None)
                defaultseriesnode['HasConfidenceLimits'].setValue(hasconfidencelimits)
                if hasconfidencelimits:
                    ubound = varslice.ubound
                    if ubound==None: ubound = varslice.data
                    lbound = varslice.lbound
                    if lbound==None: lbound = varslice.data
                    
                    if seriesnode['LineProperties/MarkerType'].getValue(usedefault=True)==0:
                        defaultseriesnode['ConfidenceLimits/Style'].setValue(2)
                    else:
                        defaultseriesnode['ConfidenceLimits/Style'].setValue(1)
                    errorbartype = seriesnode['ConfidenceLimits/Style'].getValue(usedefault=True)
                    
                    if errorbartype==0:
                        pass
                    elif errorbartype==1:
                        # Plot error bars
                        xerr = None
                        yerr = numpy.vstack((varslice.data-lbound,ubound-varslice.data))
                        if switchaxes: xerr,yerr = yerr,xerr
                        (line,errbars) = axes.errorbar(X,Y,fmt=None,xerr=xerr,yerr=yerr,ecolor=plotargs['color'],zorder=zorder)
                    elif errorbartype==2:
                        # Plot shaded confidence area (filled polygon)
                        errX = numpy.hstack((varslice.coords[0],varslice.coords[0][::-1]))
                        errY = numpy.hstack((lbound,ubound[::-1]))
                        if switchaxes: errX,errY = errY,errX
                        areacolor = seriesnode['LineProperties/Color'].getValue(usedefault=True)
                        areacolor.brighten(.5)
                        alpha = .7
                        axes.fill(errX,errY,facecolor=areacolor.getNormalized(),linewidth=0, alpha=alpha, zorder=zorder)
                    else:
                        assert False, 'Unknown error bar type %i.' % errorbartype
                    zorder += 1
                
                # Plot line and/or markers
                if plotargs['linestyle']!='' or plotargs['marker']!='':
                    hline = axes.plot(X,Y,zorder=zorder,label=label,**plotargs)
                    legenddata['handles'].append(hline)
                    legenddata['labels'].append(label)
                
                dim2data[xname]['axis'] = 'x'
                dim2data[yname]['axis'] = 'y'
                
                plotcount[1] += 1
            elif varslice.ndim==2:
                # Two-dimensional coordinate space (x,y). Use x-axis for first coordinate dimension,
                # and y-axis for second coordinate dimension.
                xdim = 0
                ydim = 1
                prefaxis = (dim2data[varslice.dimensions[0]]['preferredaxis'],dim2data[varslice.dimensions[1]]['preferredaxis'])
                if (prefaxis[0]=='y' and prefaxis[1]!='y') or (prefaxis[1]=='x' and prefaxis[0]!='x'):
                    # One independent dimension prefers to switch axis and the
                    # other does not disagree.
                    xdim = 1
                    ydim = 0

                dim2data[varslice.dimensions[xdim]]['axis'] = 'x'
                dim2data[varslice.dimensions[ydim]]['axis'] = 'y'
                
                if plottype3d!=2:
                    dim2data[varpath]['axis'] = 'colorbar'

                X = coords[xdim]
                Y = coords[ydim]
                Z = varslice.data
                
                # Get length of coordinate dimensions. Coordinates can be provided as vectors
                # valid over the whole domain, or as n-D array that match the shape of the values.
                if X.ndim==1:
                    xlength = X.shape[0]
                else:
                    xlength = X.shape[xdim]
                if Y.ndim==1:
                    ylength = Y.shape[0]
                else:
                    ylength = Y.shape[ydim]
                    
                # Adjust X dimension.
                if X.ndim==1:
                    X = X.reshape((1,-1)).repeat(ylength, 0)
                elif xdim<ydim:
                    X = X.transpose()
                    
                # Adjust Y dimension.
                if Y.ndim==1:
                    Y = Y.reshape((-1,1)).repeat(xlength, 1)
                elif xdim<ydim:
                    Y = Y.transpose()
                    
                # Adjust Z dimension.
                if xdim<ydim:
                    Z = Z.transpose()
                
                pc = None
                norm = None
                logscale = dim2data.get('colorbar',{}).get('logscale',False)
                if logscale: norm = matplotlib.colors.LogNorm()

                if plottype3d==1 or plottype3d==2:
                    loc = None
                    if logscale: loc = matplotlib.ticker.LogLocator()

                    cc = seriesnode['ContourCount'].getValue()
                    showedges = seriesnode['ShowEdges'].getValue(usedefault=True)
                    edgecolor = (seriesnode['EdgeColor'].getValue(usedefault=True).getNormalized(),)
                    if plottype3d==2 and seriesnode['UseColorMap'].getValue(usedefault=True): edgecolor = None
                    edgewidth = seriesnode['EdgeWidth'].getValue(usedefault=True)
                    borders,fill = (showedges or plottype3d==2),plottype3d==1
                    cset,csetf = None,None
                    if cc!=None:
                        if fill:
                            csetf = axes.contourf(X,Y,Z,cc,norm=norm,locator=loc,zorder=zorder,cmap=cm)
                        if borders:
                            if fill: zorder += 1
                            contourcm = cm
                            if edgecolor!=None: contourcm = None
                            cset = axes.contour(X,Y,Z,cc,norm=norm,locator=loc,zorder=zorder,colors=edgecolor,linewidths=edgewidth,cmap=contourcm)
                    else:
                        if fill:
                            csetf = axes.contourf(X,Y,Z,norm=norm,locator=loc,zorder=zorder,cmap=cm)
                        if borders:
                            if fill: zorder += 1
                            contourcm = cm
                            if edgecolor!=None: contourcm = None
                            cset = axes.contour(X,Y,Z,norm=norm,locator=loc,zorder=zorder,colors=edgecolor,linewidths=edgewidth,cmap=contourcm)
                    #if not fill: axes.clabel(cset)
                    if cc==None:
                      constset = csetf
                      if constset==None: constset = cset
                      defaultseriesnode['ContourCount'].setValue(len(constset.levels)-2)
                    pc = csetf
                    hascolormap = True
                else:
                    #edgecolors = 'None'
                    #if seriesnode['ShowEdges'].getValue(usedefault=True): edgecolors = 'k'
                    shading = 'flat'
                    if seriesnode['ShowEdges'].getValue(usedefault=True): shading = 'faceted'
                    pc = axes.pcolormesh(X,Y,Z,cmap=cm,norm=norm,shading=shading)
                    hascolormap = True
                  
                if pc!=None:
                    # Create colorbar
                    assert cb==None, 'Currently only one object that needs a colorbar is supported per figure.'
                    if isinstance(Z,matplotlib.numerix.ma.MaskedArray):
                        flatZ = Z.compressed()
                    else:
                        flatZ = Z.ravel()
                    if (flatZ==flatZ[0]).all():
                        # All z values are equal. Explicitly set color range,
                        # because MatPlotLib 0.90.0 chokes on identical min and max.
                        pc.set_clim((Z[0,0]-1,Z[0,0]+1))
                    else:
                        pc.set_clim(dim2data.get('colorbar',{}).get('forcedrange',(None,None)))
                    cb = self.figure.colorbar(pc)

                plotcount[2] += 1
            
            # Increase z-order.
            zorder += 1

            # Hold all plot properties so we can plot additional data series.
            axes.hold(True)

        # Remove unused default series
        # (remaining from previous plots that had these other data series)
        for oldname in olddefaults:
            defaultdatanode.removeChild('Series',oldname)

        # Create and store title
        title = ''
        if titles:
            title = titles[0]
            for ln in titles[1:]:
                if ln!=title:
                    title = ', '.join(titles)
                    break
        self.defaultproperties['Title'].setValue(title)
        title = self.properties['Title'].getValue(usedefault=True)
        assert title!=None, 'Title must be available, either explicitly set or as default.'
        if title!='': axes.set_title(title,size=fontsizes['axes.titlesize'],fontname=fontfamily)
        
        # Show legend
        legend = None
        self.defaultproperties['CanHaveLegend'].setValue(plotcount[1]>0)
        if plotcount[1]>0:
            self.defaultproperties['Legend'].setValue(plotcount[1]>1)
            legprop = self.properties['Legend']
            if legprop.getValue(usedefault=True):
                legend = axes.legend(legenddata['handles'],legenddata['labels'],loc=legprop['Location'].getValue(usedefault=True),prop=matplotlib.font_manager.FontProperties(size=fontsizes['legend'],family=fontfamily))
                #legend = self.figure.legend(legenddata['handles'],legenddata['labels'],1,prop=matplotlib.font_manager.FontProperties(size=fontsizes['legend'],family=fontfamily))
                legend.set_zorder(zorder)
                zorder += 1

        # Set whether the figure uses a colormap
        self.defaultproperties['HasColorMap'].setValue(hascolormap)

        # Build table linking axis to data dimension.
        axis2dim = dict([(dat['axis'],dim) for dim,dat in dim2data.iteritems() if 'axis' in dat])

        # Transform axes to log-scale where specified.
        for axisname in ('x','y','z','colorbar'):
            if axisname not in axis2dim: continue
            
            # Get default and forced axis properties
            axisnode = forcedaxes.getChildById('Axis',axisname,create=True)
            defaxisnode = defaultaxes.getChildById('Axis',axisname,create=True)
            
            # Determine whether the axis can be log-transformed.
            dimdata = dim2data[axis2dim[axisname]]
            datarange = dimdata['datarange']
            canhavelogscale = dimdata['datatype']!='datetime' and (datarange[0]>0 or datarange[1]>0)
            
            # Set log transformation defaults.
            defaxisnode['LogScale'].setValue(False)
            defaxisnode['CanHaveLogScale'].setValue(canhavelogscale)
            
            # Log transform axis if needed.
            if not (canhavelogscale and axisnode['LogScale'].getValue(usedefault=True)):
                continue
            if axisname=='x':
                axes.set_xscale('log')
            elif axisname=='y':
                axes.set_yscale('log')

        # Get effective ranges for each dimension (based on forced limits and natural data ranges)
        oldaxes    = [node.getSecondaryId() for node in forcedaxes.getLocationMultiple(['Axis'])]
        olddefaxes = [node.getSecondaryId() for node in defaultaxes.getLocationMultiple(['Axis'])]
        for axisname in ('x','y','z','colorbar'):
            if axisname not in axis2dim: continue
            
            dim = axis2dim[axisname]
            dat = dim2data[dim]
            istimeaxis = dat['datatype']=='datetime'
            
            # Get the explicitly set and the default properties.
            axisnode = forcedaxes.getChildById('Axis',axisname,create=True)
            defaxisnode = defaultaxes.getChildById('Axis',axisname,create=True)
            if axisname in oldaxes: oldaxes.remove(axisname)
            if axisname in olddefaxes: olddefaxes.remove(axisname)

            # Range selected by MatPlotLib
            if axisname=='x' and not dat.get('tight',True):
                naturalrange = axes.get_xlim()
            elif axisname=='y' and not dat.get('tight',True):
                naturalrange = axes.get_ylim()
            else:
                naturalrange = dat['datarange'][:]
                
            # Get range forced by user
            if istimeaxis:
                mintime,maxtime = axisnode['MinimumTime'].getValue(),axisnode['MaximumTime'].getValue()
                if mintime!=None: mintime = common.date2num(mintime)
                if maxtime!=None: maxtime = common.date2num(maxtime)
                forcedrange = [mintime,maxtime]
            else:
                forcedrange = [axisnode['Minimum'].getValue(),axisnode['Maximum'].getValue()]
                
            # Make sure forced ranges are valid if log transform is applied.
            if axisnode['LogScale'].getValue(usedefault=True):
                if forcedrange[0]<=0: forcedrange[0] = None
                if forcedrange[1]<=0: forcedrange[1] = None
                if naturalrange[0]<=0:
                    if axisname=='x':
                        naturalrange[0] = axes.get_xlim()[0]
                    elif axisname=='y':
                        naturalrange[0] = axes.get_ylim()[0]
            
            # Effective range used by data, after taking forced range into account.
            effdatarange = dat['datarange'][:]
            if forcedrange[0]!=None: effdatarange[0] = forcedrange[0]
            if forcedrange[1]!=None: effdatarange[1] = forcedrange[1]

            # Effective forced range, combining natural range with user overrides.
            effrange = list(forcedrange)
            if effrange[0]==None: effrange[0]=naturalrange[0]
            if effrange[1]==None: effrange[1]=naturalrange[1]
            
            # Build default label for this axis
            deflab = dat['label']
            if dat['unit']!='' and dat['unit']!=None: deflab += ' ('+dat['unit']+')'
            
            # Set default axis properties.
            defaxisnode['Label'].setValue(deflab)
            defaxisnode['Unit'].setValue(dat['unit'])
            defaxisnode['TicksMajor'].setValue(True)
            defaxisnode['TicksMajor/ShowLabels'].setValue(True)
            defaxisnode['TicksMinor'].setValue(False)
            defaxisnode['TicksMinor/ShowLabels'].setValue(False)
            defaxisnode['IsTimeAxis'].setValue(istimeaxis)

            # Get the MatPlotLib axis object.
            if axisname=='x':
                mplaxis = axes.get_xaxis()
            elif axisname=='y':
                mplaxis = axes.get_yaxis()
            else:
                mplaxis = cb.ax.get_yaxis()

            if istimeaxis:
                assert axisname!='colorbar', 'The color bar cannot be a time axis.'
                
                # Tick formats
                #DATEFORM number   DATEFORM string         Example
                #   0             'dd-mmm-yyyy HH:MM:SS'   01-Mar-2000 15:45:17 
                #   1             'dd-mmm-yyyy'            01-Mar-2000  
                #   2             'mm/dd/yy'               03/01/00     
                #   3             'mmm'                    Mar          
                #   4             'm'                      M            
                #   5             'mm'                     3            
                #   6             'mm/dd'                  03/01        
                #   7             'dd'                     1            
                #   8             'ddd'                    Wed          
                #   9             'd'                      W            
                #  10             'yyyy'                   2000         
                #  11             'yy'                     00           
                #  12             'mmmyy'                  Mar00        
                #  13             'HH:MM:SS'               15:45:17     
                #  14             'HH:MM:SS PM'             3:45:17 PM  
                #  15             'HH:MM'                  15:45        
                #  16             'HH:MM PM'                3:45 PM     
                #  17             'QQ-YY'                  Q1-01        
                #  18             'QQ'                     Q1        
                #  19             'dd/mm'                  01/03        
                #  20             'dd/mm/yy'               01/03/00     
                #  21             'mmm.dd,yyyy HH:MM:SS'   Mar.01,2000 15:45:17 
                #  22             'mmm.dd,yyyy'            Mar.01,2000  
                #  23             'mm/dd/yyyy'             03/01/2000 
                #  24             'dd/mm/yyyy'             01/03/2000 
                #  25             'yy/mm/dd'               00/03/01 
                #  26             'yyyy/mm/dd'             2000/03/01 
                #  27             'QQ-YYYY'                Q1-2001        
                #  28             'mmmyyyy'                Mar2000                               
                tickformats = {0:'%d-%b-%Y %H:%M:%S',
                                1:'%d-%b-%Y',
                                2:'%m/%d/%y',
                                3:'%b',
                                4:'%n',
                                5:'%m',
                                6:'%m/%d',
                                7:'%d',
                                8:'%a',
                                9:'%e',
                                10:'%Y',
                                11:'%y',
                                12:'%b%y',
                                13:'%H:%M:%S',
                                14:'%I:%M:%S %p',
                                15:'%H:%M',
                                16:'%I:%M %p',
                                17:'%Q-%y',
                                18:'%Q',
                                19:'%d/%m',
                                20:'%d/%m/%y',
                                21:'%b.%d,%Y %H:%M:%S',
                                22:'%b.%d,%Y',
                                23:'%m/%d/%Y',
                                24:'%d/%m/%Y',
                                25:'%y/%m/%d',
                                26:'%Y/%m/%d',
                                27:'%Q-%Y',
                                28:'%b%Y'}
                
                # Major ticks
                dayspan = (effdatarange[1]-effdatarange[0])
                location,interval,tickformat,tickspan = getTimeTickSettings(dayspan,axisnode['TicksMajor'],defaxisnode['TicksMajor'])
                mplaxis.set_major_locator(getTimeLocator(location,interval))
                assert tickformat in tickformats, 'Unknown tick format %i.' % tickformat
                mplaxis.set_major_formatter(CustomDateFormatter(tickformats[tickformat]))

                # Minor ticks
                location,interval,tickformat,tickspan = getTimeTickSettings(min(tickspan,dayspan),axisnode['TicksMinor'],defaxisnode['TicksMinor'])
                mplaxis.set_minor_locator(getTimeLocator(location,interval))
                assert tickformat in tickformats, 'Unknown tick format %i.' % tickformat
                #mplaxis.set_minor_formatter(CustomDateFormatter(tickformats[tickformat]))

                # Set the "natural" axis limits based on the data ranges.
                defaxisnode['MinimumTime'].setValue(common.num2date(naturalrange[0]))
                defaxisnode['MaximumTime'].setValue(common.num2date(naturalrange[1]))
            else:
                # Set the "natural" axis limits based on the data ranges.
                defaxisnode['Minimum'].setValue(naturalrange[0])
                defaxisnode['Maximum'].setValue(naturalrange[1])

            # Remove axis ticks if required.
            if not axisnode['TicksMajor'].getValue(usedefault=True):
                mplaxis.set_major_locator(matplotlib.ticker.FixedLocator([]))
            if not axisnode['TicksMinor'].getValue(usedefault=True):
                mplaxis.set_minor_locator(matplotlib.ticker.FixedLocator([]))

            # Obtain label for axis.
            label = axisnode['Label'].getValue(usedefault=True)
            if label==None: label=''

            # Set axis labels and boundaries.
            if axisname=='x':
                if label!='': axes.set_xlabel(label,size=fontsizes['axes.labelsize'],fontname=fontfamily)
                axes.set_xlim(effrange[0],effrange[1])
            elif axisname=='y':
                if label!='': axes.set_ylabel(label,size=fontsizes['axes.labelsize'],fontname=fontfamily)
                axes.set_ylim(effrange[0],effrange[1])
            elif axisname=='colorbar':
                assert cb!=None, 'No colorbar has been created.'
                if label!='': cb.set_label(label,size=fontsizes['axes.labelsize'],fontname=fontfamily)

        for oldaxis in oldaxes:
            forcedaxes.removeChild('Axis',oldaxis)
        for oldaxis in olddefaxes:
            defaultaxes.removeChild('Axis',oldaxis)

        # Create grid
        gridnode = self.properties['Grid']
        if gridnode.getValue(usedefault=True):
            lineargs = getLineProperties(gridnode['LineProperties'])
            axes.grid(True,**lineargs)
        
        # Scale the text labels for x- and y-axis.
        for l in axes.get_xaxis().get_ticklabels():
            l.set_size(fontsizes['xtick.labelsize'])
            l.set_name(fontfamily)
        for l in axes.get_yaxis().get_ticklabels():
            l.set_size(fontsizes['ytick.labelsize'])
            l.set_name(fontfamily)
        offset = axes.get_xaxis().get_offset_text()
        offset.set_size(fontsizes['xtick.labelsize'])
        offset.set_name(fontfamily)
        offset = axes.get_yaxis().get_offset_text()
        offset.set_size(fontsizes['ytick.labelsize'])
        offset.set_name(fontfamily)
        
        # Scale text labels for color bar.
        if cb!=None:
            offset = cb.ax.yaxis.get_offset_text()
            offset.set_size(fontsizes['ytick.labelsize'])
            offset.set_name(fontfamily)
            for l in cb.ax.yaxis.get_ticklabels():
                l.set_size(fontsizes['ytick.labelsize'])
                l.set_name(fontfamily)

        # Draw the plot to screen.
        self.canvas.draw()
        
        for cb in self.callbacks['completeStateChange']: cb(len(forcedseries)>0)

        self.dirty = False
        
def setLineProperties(propertynode,mplsection='lines',**kwargs):
    """Sets the values under a xmlstore.TypedStore node describing line
    properties all at once.
    
    Internal use only. Used to quickly set default line properties.
    """
    deflinewidth = matplotlib.rcParams[mplsection+'.linewidth']
    deflinecolor = matplotlib.rcParams[mplsection+'.color']
    deflinecolor = matplotlib.colors.colorConverter.to_rgb(deflinecolor)
    deflinecolor = xmlstore.xmlstore.StoreColor.fromNormalized(*deflinecolor)
    deflinestyle = matplotlib.rcParams[mplsection+'.linestyle']
    linestyles = {'-':1,'--':2,'-.':3,':':4}
    if deflinestyle in linestyles:
        deflinestyle = linestyles[deflinestyle]
    else:
        deflinestyle = 0
    defmarkersize = matplotlib.rcParams.get(mplsection+'.markersize',6.)

    propertynode['CanHaveMarker'].setValue(kwargs.get('CanHaveMarker',True))
    propertynode['LineStyle'].setValue(kwargs.get('LineStyle',deflinestyle))
    propertynode['LineWidth'].setValue(kwargs.get('LineWidth',deflinewidth))
    propertynode['Color'].setValue(kwargs.get('Color',deflinecolor))
    propertynode['MarkerType'].setValue(kwargs.get('MarkerType',0))
    propertynode['MarkerSize'].setValue(kwargs.get('MarkerSize',defmarkersize))
    propertynode['MarkerFaceColor'].setValue(kwargs.get('MarkerFaceColor',deflinecolor))
    
def getLineProperties(propertynode):
    """Returns a dictionary with line properties based on the specified
    xmlstore.TypedStore node.
    
    Internal use only.
    """
    markertype = propertynode['MarkerType'].getValue(usedefault=True)
    markertypes = {0:'',1:'.',2:',',3:'o',4:'^',5:'s',6:'+',7:'x',8:'D'}
    markertype = markertypes[markertype]
    
    linestyle = propertynode['LineStyle'].getValue(usedefault=True)
    linestyles = {0:'',1:'-',2:'--',3:'-.',4:':'}
    linestyle = linestyles[linestyle]
    
    linewidth = propertynode['LineWidth'].getValue(usedefault=True)
    color = propertynode['Color'].getValue(usedefault=True)
    markersize = propertynode['MarkerSize'].getValue(usedefault=True)
    markerfacecolor = propertynode['MarkerFaceColor'].getValue(usedefault=True)
    
    return {'linestyle':linestyle,'marker':markertype,'linewidth':linewidth,'color':color.getNormalized(),'markersize':markersize,'markerfacecolor':markerfacecolor.getNormalized()}
    
def getTimeLocator(location,interval):
    """Creates a time locator based on the unit ("location") and interval
    chosen.
    
    Internal use only.
    """
    if location==0:
        return matplotlib.dates.YearLocator(base=interval)
    elif location==1:
        return matplotlib.dates.MonthLocator(interval=interval)
    elif location==2:
        return matplotlib.dates.DayLocator(interval=interval)
    elif location==3:
        return matplotlib.dates.HourLocator(interval=interval)
    elif location==4:
        return matplotlib.dates.MinuteLocator(interval=interval)
    else:
        assert False, 'unknown tick location %i' % location
    
def getTimeTickSettings(dayspan,settings,defsettings,preferredcount=8):
    """Reads the time tock settings from the specified TypedStore.xmlstore node.
    
    Internal use only.
    """
    unitlengths = {0:365,1:30.5,2:1.,3:1/24.,4:1/1440.}
    if dayspan/365>=2:
        location,tickformat = 0,10
    elif dayspan>=61:
        location,tickformat = 1,4
    elif dayspan>=2:
        location,tickformat = 2,19
    elif 24*dayspan>=2:
        location,tickformat = 3,15
    else:
        location,tickformat = 4,15

    defsettings['LocationTime'].setValue(location)
    defsettings['FormatTime'].setValue(tickformat)
    location   = settings['LocationTime'].getValue(usedefault=True)
    tickformat = settings['FormatTime'].getValue(usedefault=True)

    # Calculate optimal interval between ticks, aiming for max. 8 ticks total.
    tickcount = dayspan/unitlengths[location]
    interval = math.ceil(float(tickcount)/preferredcount)
    if interval<1: interval = 1
    
    # Save default tick interval, then get effective tick interval.
    defsettings['IntervalTime'].setValue(interval)
    interval = settings['IntervalTime'].getValue(usedefault=True)

    # Make sure we do not plot more than 100 ticks: non-informative and very slow!
    if tickcount/interval>100: interval=math.ceil(tickcount/100.)
    
    return location,interval,tickformat,interval*unitlengths[location]