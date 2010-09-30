"""
Set of functions to evalutate the masking and reconstruction procedures

T. Bertin-Mahieux (2010) Columbia University
tb2332@columbia.edu
"""

import os
import sys
import glob
import numpy as np
import scipy.io as sio
from scipy import histogram
import scipy.spatial.distance as DIST
import scipy.stats.distributions as DISTRIBS

import imputation as IMPUTATION
import imputation_plca as IMPUTATION_PLCA
import hmm_imputation as IMPUTATION_HMM
try:
    import kalman_toolbox as KALMAN
except ImportError:
    print 'cant import KALMAN: no matlab maybe?'
import masking as MASKING

EPS = np.finfo(np.float).eps


def euclidean_dist_sq(v1,v2):
    """
    Trivial averaged squared euclidean distance from too flatten vectors
    """
    return np.square(v1.flatten()-v2.flatten()).mean()

def cosine_dist(v1,v2):
    """
    Consine distance between too flatten vector
    """
    return DIST.cosine(v1.flatten(),v2.flatten())

def symm_kl_div(v1,v2):
    """
    Normalize and return the symmetric kldivergence
    """
    v1 = v1.copy() / v1.sum() + EPS
    v2 = v2.copy() / v2.sum() + EPS
    assert not np.isnan(v1).any()
    assert not np.isnan(v2).any()
    res1 = (v1 * np.log(v1 / v2))
    res2 = (v2 * np.log(v2 / v1))
    res1[np.where(np.isnan(res1))] = 0.
    res2[np.where(np.isnan(res2))] = 0.
    div1 = res1.sum()
    div2 = res2.sum()
    return (div1 + div2) / 2.


def entropy(v1):
    """
    Computes entropy, sum -p_i * log(p_i)
    """
    return DISTRIBS.entropy(v1.flatten())

def abs_n_ent_diff(v1,v2,nbins=10):
    """
    Absolute normalized entropy difference, between v1 and v2
    (not symmetric!)
    Quantized the values in 100 bins, measure entropy
    of each of those bins, look at the difference of
    entropy between the two distributions for each of
    those bins.
    nbins  - quantization level between 0 and 1
    """
    assert v1.size == v2.size,'v1 and v2 different sizes'
    edges = np.array(range(0,nbins+1),'float') / nbins
    h1 = histogram(v1.flatten(),edges)[0] + 2
    h2 = histogram(v2.flatten(),edges)[0] + 2
    ents1 = -np.log2(h1*1./h1.sum())
    ents2 = -np.log2(h2*1./h2.sum())
    return np.abs(((ents1 - ents2)/ents1)).mean()


def recon_error(btchroma,mask,recon,measure='all'):
    """

    INPUT
       btchroma   - original feature matrix
       mask       - binary mask, same shape as btchroma
       recon      - reconstruction, same shape as btchroma
       measure    - 'eucl' (euclidean distance, default)
                  - 'kl' (symmetric KL-divergence)
                  - 'cos' (cosine distance)
                  - 'dent' (absolute normalized difference of entropy)
                  - 'all' returns a dictionary with all the above
    RETURN
       div        - divergence, or reconstruction error
    """
    # sanity checks
    assert btchroma.shape == mask.shape,'bad mask shape'
    assert btchroma.shape == recon.shape,'bad recon shape'
    # get measure function
    if measure == 'eucl':
        measfun = euclidean_dist_sq
    elif measure == 'kl':
        measfun = symm_kl_div
    elif measure == 'cos':
        measfun = cosine_dist
    elif measure == 'dent':
        measfun = abs_n_ent_diff
    elif measure == 'all':
        pass
    else:
        raise ValueError('wrong measure name, want eucl or kl?')
    if measure is not 'all':
        # measure and done
        maskzeros = np.where(mask==0)
        return measfun( btchroma[maskzeros] , recon[maskzeros] )
    else:
        meas = ('eucl','kl','cos','dent')
        ds = map(lambda m: recon_error(btchroma,mask,recon,m), meas)
        return dict( zip(meas, ds) )
            


def get_all_matfiles(basedir) :
    """
    From a root directory, go through all subdirectories
    and find all matlab files. Return them in a list.
    """
    allfiles = []
    for root, dirs, files in os.walk(basedir):
        matfiles = glob.glob(os.path.join(root,'*.mat'))
        for f in matfiles :
            allfiles.append( os.path.abspath(f) )
    return allfiles



def test_maskedcol_on_dataset(datasetdir,method='random',ncols=1,win=3,rank=4,codebook=None,**kwargs):
    """
    General method to test a method on a whole dataset for one masked column
    Methods are:
      - random
      - randomfromsong
      - average
      - codebook
      - knn_eucl
      - knn_kl
      - lintrans
      - siplca
      - siplca2
    Used arguments vary based on the method. For SIPLCA, we can use **kwargs
    to set priors.
    """
    MINLENGTH = 70
    # get all matfiles
    matfiles = get_all_matfiles(datasetdir)
    # init
    total_cnt = 0
    errs_eucl = []
    errs_kl = []
    # some specific inits
    if codebook != None and not type(codebook) == type([]):
        codebook = [p.reshape(12,codebook.shape[1]/12) for p in codebook]
        print 'codebook in ndarray format transformed to list'
    # iterate
    for matfile in matfiles:
        btchroma = sio.loadmat(matfile)['btchroma']
        if btchroma.shape[1] < MINLENGTH or np.isnan(btchroma).any():
            continue
        mask,masked_cols = MASKING.random_col_mask(btchroma,ncols=ncols,win=25)
        ########## ALGORITHM DEPENDENT
        if method == 'random':
            recon = IMPUTATION.random_col(btchroma,mask,masked_cols)
        elif method == 'randomfromsong':
            recon = IMPUTATION.random_col_from_song(btchroma,mask,masked_cols)
        elif method == 'average':
            recon = IMPUTATION.average_col(btchroma,mask,masked_cols,win=win)
        elif method == 'codebook':
            recon,used_codes = IMPUTATION.codebook_cols(btchroma,mask,masked_cols,codebook)
        elif method == 'knn_eucl':
            recon,used_cols = IMPUTATION.knn_cols(btchroma,mask,masked_cols,win=win,measure='eucl')
        elif method == 'knn_kl':
            recon,used_cols = IMPUTATION.knn_cols(btchroma,mask,masked_cols,win=win,measure='kl')
        elif method == 'lintrans':
            recon,proj = IMPUTATION.lintransform_cols(btchroma,mask,masked_cols,win=win)
        elif method == 'siplca':
            res = IMPUTATION_PLCA.SIPLCA_mask.analyze((btchroma*mask).copy(),
                                                      rank,mask,win=win,
                                                      convergence_thresh=1e-15,
                                                      **kwargs)
            W, Z, H, norm, recon, logprob = res
        elif method == 'siplca2':
            res = IMPUTATION_PLCA.SIPLCA2_mask.analyze((btchroma*mask).copy(),
                                                       rank,mask,win=win,
                                                       convergence_thresh=1e-15,
                                                       **kwargs)
            W, Z, H, norm, recon, logprob = res
        else:
            print 'unknown method:',method
            return
        ########## ALGORITHM DEPENDENT END
        # measure recon
        err = recon_error(btchroma,mask,recon,measure='eucl')
        if err > 100:
            print 'huge EUCL error:',err,', method =',method,',file =',matfile
        errs_eucl.append( err )
        err = recon_error(btchroma,mask,recon,measure='kl')
        if err > 100:
            print 'huge KL error:',err,', method =',method,',file =',matfile
        errs_kl.append( err )
        total_cnt += 1
    # done
    print 'number of songs tested:',total_cnt
    print 'average sq euclidean dist:',np.mean(errs_eucl),'(',np.std(errs_eucl),')'
    print 'average kl divergence:',np.mean(errs_kl),'(',np.std(errs_kl),')'


def test_maskedpatch_on_dataset(dataset,method='random',ncols=2,win=1,rank=4,codebook=None,nstates=1,verbose=1,**kwargs):
    """
    Dataset is either dir, or list of files
    General method to test a method on a whole dataset for one masked column
    Methods are:
      - random
      - randomfromsong
      - average
      - averageall
      - codebook
      - knn_eucl
      - knn_kl
      - lintrans
      - kalman
      - hmm
      - siplca
      - siplca2
    Used arguments vary based on the method. For SIPLCA, we can use **kwargs
    to set priors.
    """
    MINLENGTH = 70
    # get all matfiles
    if type(dataset).__name__ == 'str':
        matfiles = get_all_matfiles(dataset)
    else:
        matfiles = dataset
    # init
    total_cnt = 0
    all_errs = []
    # some specific inits
    if codebook != None and not type(codebook) == type([]):
        codebook = [p.reshape(12,codebook.shape[1]/12) for p in codebook]
        print 'codebook in ndarray format transformed to list'
    # iterate
    for matfile in matfiles:
        btchroma = sio.loadmat(matfile)['btchroma']
        if btchroma.shape[1] < MINLENGTH or np.isnan(btchroma).any():
            continue
        mask,p1,p2 = MASKING.random_patch_mask(btchroma,ncols=ncols,win=25)
        ########## ALGORITHM DEPENDENT
        if method == 'random':
            recon = IMPUTATION.random_patch(btchroma,mask,p1,p2)
        elif method == 'randomfromsong':
            recon = IMPUTATION.random_patch_from_song(btchroma,mask,p1,p2)
        elif method == 'average':
            recon = IMPUTATION.average_patch(btchroma,mask,p1,p2,win=win)
        elif method == 'averageall':
            recon = IMPUTATION.average_patch_all(btchroma,mask,p1,p2)
        elif method == 'codebook':
            recon,used_codes = IMPUTATION.codebook_patch(btchroma,mask,p1,p2,codebook)
        elif method == 'knn_eucl':
            recon,used_cols = IMPUTATION.knn_patch(btchroma,mask,p1,p2,win=win,measure='eucl')
        elif method == 'knn_kl':
            recon,used_cols = IMPUTATION.knn_patch(btchroma,mask,p1,p2,win=win,measure='kl')
        elif method == 'lintrans':
            recon,proj = IMPUTATION.lintransform_patch(btchroma,mask,p1,p2,win=win)
        elif method == 'kalman':
            recon = KALMAN.imputation(btchroma,p1,p2,
                                      dimstates=nstates,**kwargs)
        elif method == 'hmm':
            recon,recon2,hmm = IMPUTATION_HMM.imputation(btchroma*mask,p1,p2,
                                                         nstates=nstates,
                                                         **kwargs)
        elif method == 'siplca':
            res = IMPUTATION_PLCA.SIPLCA_mask.analyze((btchroma*mask).copy(),
                                                      rank,mask,win=win,
                                                      convergence_thresh=1e-15,
                                                      **kwargs)
            W, Z, H, norm, recon, logprob = res
        elif method == 'siplca2':
            res = IMPUTATION_PLCA.SIPLCA2_mask.analyze((btchroma*mask).copy(),
                                                       rank,mask,win=win,
                                                       convergence_thresh=1e-15,
                                                       **kwargs)
            W, Z, H, norm, recon, logprob = res
        else:
            print 'unknown method:',method
            return
        ########## ALGORITHM DEPENDENT END
        # measure recon
        errs = recon_error(btchroma,mask,recon,measure='all')
        all_errs.append( errs )
        total_cnt += 1
    # done
    if verbose > 0:
        print 'number of songs tested:',total_cnt
        for meas in np.sort(all_errs[0].keys()):
            errs = map(lambda d: d[meas], all_errs)
            print 'average',meas,'=',np.mean(errs),'(',np.std(errs),')'
    return all_errs



    
def cut_train_test_by_numbers(datasetdir,nums=[5000,5000],seed=666999):
    """
    Get all songs from datasetdir.
    Order them by name, then shuffle (we know the seed!)
    Return two list of files, for train and for test, according to numbers
    in nums.
    Of course, files are not overlapping.
    If we change one number, the same files remained used for the other set
    (after shuffling, train is taken from the beggining of the list,
    test is taken from the end).
    """
    # sanity check
    assert len(nums)==2,'we need a list of two numbers'
    # get all matfiles
    matfiles = map(lambda x: os.path.abspath(x),get_all_matfiles(datasetdir))
    # check if we have enough files
    assert len(matfiles)>=nums[0] + nums[1],'not enough files for number requested'
    # order by name
    matfiles = np.sort(matfiles)
    # shuffle
    np.random.seed(seed)
    np.random.shuffle(matfiles)
    # cut
    train = list( matfiles[:nums[0]] )
    test = list( matfiles[-nums[1]:] )
    # done
    return train, test


def measure_nice_name(measure):
    """
    Receives a measure code: 'eucl','cos','kl','dent'
    and returns a reasonable string
    """
    if measure == 'eucl':
        return 'euclidean distance'
    if measure == 'cos':
        return 'cosine distance'
    if measure == 'kl':
        return 'KL symm. divergence'
    if measure == 'dent':
        return 'absolute entropy difference'
    print 'unknown measure:',measure
    return 'unknown'


def plot_2_measures_dataset(dataset,methods=(),methods_args=(),measures=(),ncols=(),verbose=1):
    """
    Plot 2 measures and display algorithms (methods) in it
    INPUT
       dataset      - directory path, or list of files
       methods      - list of method names
       methods_args - list of dictionaries, to be passed as params
    """
    # sanity checks
    for meas in measures:
        assert meas in ('eucl','kl','cos','dent'),'unknown measure: '+meas
    assert len(measures) == 2,'this function need exactly 2 measures!'
    # inits
    nmethods = len(methods)
    if len(methods_args) == 0:
        methods_args = [{}] * nmethods
    err_measure1 = np.zeros((nmethods,len(ncols)))
    err_measure2 = np.zeros((nmethods,len(ncols)))
    # iterate on methods
    for imethod,method in enumerate(methods):
        if verbose>0: print 'doing method:',method
        for incol,ncol in enumerate(ncols):
            if verbose>0: print 'doing ncol:',ncol
            res = test_maskedpatch_on_dataset(dataset,method=method,ncols=ncol,
                                              verbose=verbose,
                                              **methods_args[imethod])
            err_measure1[imethod,incol] = np.mean(map(lambda d:d[measures[0]],
                                                      res))
            err_measure2[imethod,incol] = np.mean(map(lambda d:d[measures[1]],
                                                      res))
    # iterations done, let's plot
    if verbose>0: print "let's plot!"
    import pylab as P
    colors = ('b','r','g','c','m','y')
    lines = ('-','--','-.',':')
    P.figure()
    for imethod,method in enumerate(methods):
        errs1 = err_measure1[imethod,:]
        errs2 = err_measure2[imethod,:]
        P.plot(errs1,errs2,colors[imethod]+lines[imethod]+'o',label=method)
    # titles
    P.title('imputation of '+str(ncols)+' beats on '+str(len(res))+' songs.')
    P.xlabel( measure_nice_name(measures[0]) )
    P.ylabel( measure_nice_name(measures[1]) )
    P.legend()
    P.show()


def plot_oneexample(btchroma,mask,p1,p2,methods=(),methods_args=None,
                    measures=(),subplot=None,plotrange=None,**kwargs):
    """
    Utility function to plot the result of many methods on one example.
    Methods and arguments are the same as when we test on a whole dataset.
    First two plots are always original then original*mask.
    INPUT
      btchroma     - btchroma
      mask         - binary mask, 0 = hidden
      p1           - first masked column
      p2           - last masekdcolumn + 1
      methods      - list of methods (lintrans,random,....)
      bethods_args - list of dictionary containing arguments
      measures     - list of measures, put in title (we sort according to first)
      subplot      - if None, images in one column
      plotrange    - if we dont want to plot everything set to (pos1,pos2)
      kwargs       - extra arguments passed to plotall
    """
    from plottools import plotall
    # inits and sanity checks
    for meas in measures:
        assert meas in ('eucl','kl','cos','dent'),'unknown measure: '+meas
    nmethods = len(methods)
    assert nmethods > 0,'we need at least one method...!'
    if methods_args is None:
        methods_args = [{}]*len(methods)
    if subplot is None:
        subplot = (nmethods+2,1)
    assert np.zeros(subplot).size == len(methods)+2,'wrong subplot, forgot original and masked original?'
    if plotrange is None:
        plotrange = (0,btchroma.shape[1])
    # impute
    errs = []
    recons = []
    ########## ALGORITHM DEPENDENT
    for im,method in enumerate(methods):
        if method == 'random':
            recon = IMPUTATION.random_patch(btchroma,mask,p1,p2,**methods_args[im])
        elif method == 'randomfromsong':
            recon = IMPUTATION.random_patch_from_song(btchroma,mask,p1,p2,**methods_args[im])
        elif method == 'average':
            recon = IMPUTATION.average_patch(btchroma,mask,p1,p2,**methods_args[im])
        elif method == 'averageall':
            recon = IMPUTATION.average_patch_all(btchroma,mask,p1,p2,**methods_args[im])
        elif method == 'codebook':
            recon,used_codes = IMPUTATION.codebook_patch(btchroma,mask,p1,p2,**methods_args[im])
        elif method == 'knn_eucl':
            recon,used_cols = IMPUTATION.knn_patch(btchroma,mask,p1,p2,measure='eucl',**methods_args[im])
        elif method == 'knn_kl':
            recon,used_cols = IMPUTATION.knn_patch(btchroma,mask,p1,p2,measure='kl',**methods_args[im])
        elif method == 'lintrans':
            recon,proj = IMPUTATION.lintransform_patch(btchroma,mask,p1,p2,**methods_args[im])
        elif method == 'kalman':
            recon = KALMAN.imputation(btchroma,p1,p2,**methods_args[im])
        elif method == 'hmm':
            recon,recon2,hmm = IMPUTATION_HMM.imputation(btchroma*mask,p1,p2,
                                                         **methods_args[im])
        elif method == 'siplca':
            rank = methods_args[im]['rank']
            res = IMPUTATION_PLCA.SIPLCA_mask.analyze((btchroma*mask).copy(),
                                                      rank,mask,
                                                      convergence_thresh=1e-15,
                                                      **methods_args[im])
            W, Z, H, norm, recon, logprob = res
        elif method == 'siplca2':
            rank = methods_args[im]['rank']
            res = IMPUTATION_PLCA.SIPLCA2_mask.analyze((btchroma*mask).copy(),
                                                       rank,mask,
                                                       convergence_thresh=1e-15,
                                                       **methods_args[im])
            W, Z, H, norm, recon, logprob = res
        else:
            print 'unknown method:',method
            return
        # compute errors
        recons.append( recon.copy() )
        errs.append( recon_error(btchroma,mask,recon,'all') )
    # all methods computed
    # now we sort the results according to first measure
    main_errs = map(lambda x: x[measures[0]], errs)
    order = np.array(np.argsort(main_errs))
    methods = map(lambda i: methods[i], order)
    errs = map(lambda i: errs[i], order)
    recons = map(lambda i: recons[i], order)
    # plot
    import pylab as P
    P.figure()
    pos1 = plotrange[0]
    pos2 = plotrange[1]
    ims = [btchroma[:,pos1:pos2],(btchroma*mask)[:,pos1:pos2]]
    ims.extend( map(lambda r: r[:,pos1:pos2], recons) )
    titles = ['original', 'original masked']
    for imethod,method in enumerate(methods):
        t = method + ':'
        for m in measures:
            t += ' ' + m + '=' + str(errs[imethod][m])
        titles.append(t)
    plotall(ims,subplot=subplot,title=titles,cmap='gray_r',colorbar=False)
    P.show()
