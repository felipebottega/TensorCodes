"""
Construction Module
 
 As we mentioned in the main module *Tensor Fox*, the module *Construction* is responsible for constructing the more complicated objects necessary to make computations. Between these objects we have the array of residuals, the derivative of the residuals, the starting points to begin the iterations and so on. Below we list all funtions presented in this module.
 
 - residual
 
 - residual_entries
 
 - start_point
 
 - smart_random
 
 - smart_sample
 
 - assign_values

 - smart

 - find_factor

""" 


import numpy as np
import sys
import scipy.io
import time
import matplotlib.pyplot as plt
from scipy import sparse
from numba import jit, njit, prange
import Conversion as cnv
import Auxiliar as aux
import TensorFox as tfx


@njit(nogil=True, parallel=True)
def residual(res, T, T_aux, m, n, p):
    """
    This function computes (updates) the residuals between a 3-D tensor T in R^m⊗R^n⊗R^p
    and an approximation T_approx of rank r. The tensor T_approx is of the form
    T_approx = X_1⊗Y_1⊗Z_1 + ... + X_r⊗Y_r⊗Z_r, where
    X = [X_1, ..., X_r],
    Y = [Y_1, ..., Y_r],
    Z = [Z_1, ..., Z_r].
    
    The `residual map` is a map res:R^{r+r(m+n+p)}->R^{m*n*p}. For each i,j,k=0...n, the residual 
    r_{i,j,k} is given by res_{i,j,k} = T_{i,j,k} - sum_{l=1}^r X_{il}*Y_{jl}*Z_{kl}.
    
    Inputs
    ------
    res: float 1-D ndarray with m*n*p entries 
        Each entry is a residual.
    T: float 3-D ndarray
    T_aux: float 3-D ndarray
        T_aux is the current tensor obtained by the iteration of dGN. 
    m,n,p: int
    
    Outputs
    -------
    res: float 1-D ndarray with m*n*p entries 
        Each entry is a residual.
    """   
    
    s = 0
    
    #Construction of the vector res = (res_{111}, res_{112}, ..., res_{mnp}).
    for i in prange(0,m):
        for j in range(0,n):
            for k in range(0,p):
                s = n*p*i + p*j + k
                res[s] = T[i,j,k] - T_aux[i,j,k]
                            
    return res


@njit(nogil=True)
def residual_entries(T_ijk, X, Y, Z, r, i, j, k):
    """ 
    Computation of each individual residual in the residual function. 
    """
    
    acc = 0.0
    for l in range(0,r):
        acc += X[i,l]*Y[j,l]*Z[k,l]    
    
    res_ijk = T_ijk - acc
        
    return res_ijk


def start_point(T, Tsize, S, U1, U2, U3, r, R1, R2, R3, init, ordering, symm, low, upp, factor, display):
    """
    This function generates a starting point to begin the iterations of the
    Gauss-Newton method. There are three options:
        list: the user may give a list [X,Y,Z] with the three arrays to use
    as starting point.
        'random': each entry of X, Y, Z are generated by the normal
    distribution with mean 0 and variance 1.
        'smart_random': generates a random starting point with a method which
    always guarantee a small relative error. Check the function 'smart' for 
    more details about this method.
    
    Inputs
    ------
    T: float 3-D ndarray
    Tsize: float
    S: float 3-D ndarray with shape (R1, R2, R3)
    U1: float 2-D ndarrays with shape (R1, r)
    U2: float 2-D ndarrays with shape (R2, r)
    U3: float 2-D ndarrays with shape (R3, r)
    r, R1, R2, R3: int
    init: string or list
       Method of initialization. The three methods were described above.
    symm: bool
    display: int
    
    Outputs
    -------
    X: float 2-D ndarray of shape (R1, r)
    Y: float 2-D ndarray of shape (R2, r)
    Z: float 2-D ndarray of shape (R3, r)
    rel_error: float
        Relative error associate to the starting point. More precisely, it is the relative 
    error between T and (U1,U2,U3)*S_init, where S_init = (X,Y,Z)*I.
    """
    
    if type(init) == list: 
        X = init[ordering[0]]
        Y = init[ordering[1]]
        Z = init[ordering[2]]  
        dims = [R1, R2, R3]
        X = np.dot(U1.T, X)
        Y = np.dot(U2.T, Y)
        Z = np.dot(U3.T, Z) 
                
    elif init == 'random':
        X = np.random.randn(R1, r)
        Y = np.random.randn(R2, r)
        Z = np.random.randn(R3, r)
        
    elif init == 'smart_random':
        X, Y, Z = smart_random(S, r, R1, R2, R3)

    elif init == 'smart':
        X, Y, Z = smart(S, r, R1, R2, R3)
        
    else:
        sys.exit('Error with init parameter.') 

    # Depending on the tensor, the factors X, Y, Z may have null entries. We want to
    # avoid that. The solution is to introduce some little random noise. 
    X, Y, Z = aux.clean_zeros(S, X, Y, Z)

    # Make all factors balanced.
    X, Y, Z = aux.equalize(X, Y, Z, r)

    X, Y, Z = cnv.transform(X, Y, Z, R1, R2, R3, r, low, upp, factor, symm)
    
    if display == 3:
        # Computation of relative error associated with the starting point given.
        S_init = cnv.cpd2tens([X, Y, Z], (R1, R2, R3))
        rel_error = aux.compute_error(T, Tsize, S_init, R1, R2, R3, U1, U2, U3)
        return X, Y, Z, rel_error

    return X, Y, Z


def smart_random(S, r, R1, R2, R3):
    """
    100 samples of random possible initializations are generated and compared. We
    keep the closest to S_trunc. This method draws r points in S_trunc and generates
    a tensor with rank <= r from them. The distribution is such that it tries to
    maximize the energy of the sampled tensor, so the error is minimized.
    Althought we are using the variables named as R1, R2, R3, remember they refer to
    R1_trunc, R2_trunc, R3_trunc at the main function.
    Since this function depends on the energy, it only makes sense using it when the
    original tensor can be compressed. If this is not the case, avoid using this function.
    
    Inputs
    ------
    S: 3-D float ndarray
    r: int
    R1, R2, R3: int
        The dimensions of the truncated tensor S.
    samples: int
        The number of tensors drawn randomly. Default is 100.
        
    Outputs
    -------
    X: float 2-D ndarray of shape (R1, r)
    Y: float 2-D ndarray of shape (R2, r)
    Z: float 2-D ndarray of shape (R3, r)
    """
    
    # Initialize auxiliary values and arrays.
    samples = 1 + int(np.sqrt(R1*R2*R3))
    best_error = np.inf
    Ssize = np.linalg.norm(S)
    
    # Start search for a good initial point.
    for sample in range(0,samples):
        X, Y, Z = smart_sample(S, r, R1, R2, R3)
        S_init = cnv.cpd2tens([X, Y, Z], (R1, R2, R3))
        rel_error = np.linalg.norm(S - S_init)/Ssize
        if rel_error < best_error:
            best_error = rel_error
            best_X, best_Y, best_Z = X, Y, Z

    return best_X, best_Y, best_Z


@jit(nogil=True)
def smart_sample(S, r, R1, R2, R3):
    """
    We consider a distribution that gives more probability to smaller coordinates. This 
    is because these are associated with more energy. We choose a random number c1 in the 
    integer interval [0, R1 + (R1-1) + (R1-2) + ... + 1]. If 0 <= c1 < R1, we choose i = 1,
    if R1 <= c1 < R1 + (R1-1), we choose i = 2, and so on. The same goes for the other
    coordinates.
    Let S_{i_l,j_l,k_l}, l = 1...r, be the points chosen by this method. With them we form
    the tensor S_init = sum_{l=1}^r S_{i_l,j_l,k_l} e_{i_l} ⊗ e_{j_l} ⊗ e_{k_l}, which 
    should be close to S_trunc.
    
    Inputs
    ------
    S: 3-D float ndarray
    r: int
    R1, R2, R3: int
    
    Ouputs
    ------
    X: float 2-D ndarray of shape (R1, r)
    Y: float 2-D ndarray of shape (R2, r)
    Z: float 2-D ndarray of shape (R3, r)
    """
    
    # Initialize arrays to construct initial approximate CPD.
    X = np.zeros((R1, r), dtype = np.float64)
    Y = np.zeros((R2, r), dtype = np.float64)
    Z = np.zeros((R3, r), dtype = np.float64)
    # Construct the upper bounds of the intervals.
    arr1 = R1*np.ones(R1, dtype = np.int64) - np.arange(R1)
    arr2 = R2*np.ones(R2, dtype = np.int64) - np.arange(R2)
    arr3 = R3*np.ones(R3, dtype = np.int64) - np.arange(R3)
    high1 = np.sum(arr1)
    high2 = np.sum(arr2)
    high3 = np.sum(arr3)

    # Arrays with all random choices.
    C1 = np.random.randint(high1, size=r)
    C2 = np.random.randint(high2, size=r)  
    C3 = np.random.randint(high3, size=r)

    # Update arrays based on the choices made.
    for l in range(0,r):
        X[:,l], Y[:,l], Z[:,l] = assign_values(S, X, Y, Z, r, R1, R2, R3, C1, C2, C3, arr1, arr2, arr3, l) 
          
    return X, Y, Z


@jit(nogil=True)
def assign_values(S, X, Y, Z, r, R1, R2, R3, C1, C2, C3, arr1, arr2, arr3, l):
    """
    For each l = 1...r, this function constructs l-th one rank term in the CPD of the
    initialization tensor, which is of the form S[i,j,k]*e_i ⊗ e_j ⊗ e_k for some
    i,j,k choosed through the random distribution described earlier.
    """
    
    for i in range(0,R1):
        if (np.sum(arr1[0:i]) <= C1[l]) and (C1[l] < np.sum(arr1[0:i+1])):
            X[i,l] = 1
            break
    for j in range(0,R2):
        if (np.sum(arr2[0:j]) <= C2[l]) and (C2[l] < np.sum(arr2[0:j+1])):
            Y[j,l] = 1
            break
    for k in range(0,R3):
        if (np.sum(arr3[0:k]) <= C3[l]) and (C3[l] < np.sum(arr3[0:k+1])):
            Z[k,l] = 1
            break   

    X[i,l] = S[i,j,k] 
        
    return X[:,l], Y[:,l], Z[:,l]


@njit(nogil=True)
def smart(S, r, R1, R2, R3):
    """
    Construct a truncated version of S with the r entries with higher energy.
    Let S_{i_l,j_l,k_l}, l = 1...r, be the points chosen by this method. With them we 
    form the tensor S_init = sum_{l=1}^r S_{i_l,j_l,k_l} e_{i_l} ⊗ e_{j_l} ⊗ e_{k_l}, 
    which should be close to S_trunc.
    
    Inputs
    ------
    S: 3-D float ndarray
    r: int
    R1, R2, R3: int
        The dimensions of the truncated tensor S.
            
    Outputs
    -------
    X: float 2-D ndarray of shape (R1, r)
    Y: float 2-D ndarray of shape (R2, r)
    Z: float 2-D ndarray of shape (R3, r)
    """

    # Find the entries of S with higher energy.
    largest = np.zeros(r, dtype=np.float64)
    indexes = np.zeros((r,3), dtype=np.int64)
    for i in range(R1):
        for j in range(R2):
            for k in range(R3):
                if np.abs(S[i,j,k]) > np.min(np.abs(largest)):
                    idx = np.argmin(np.abs(largest))
                    largest[idx] = S[i,j,k]
                    indexes[idx,:] = np.array([i,j,k])

    # Initialize the factors X, Y, Z.
    X = np.zeros((R1, r), dtype=np.float64)
    Y = np.zeros((R2, r), dtype=np.float64)
    Z = np.zeros((R3, r), dtype=np.float64)
    
    # Use the entries computed previously to generates the factors X, Y, Z.
    for l in range(r):
        i, j, k = indexes[l,:]
        X[i,l] = largest[l]
        Y[j,l] = 1
        Z[k,l] = 1
                    
    return X, Y, Z


def find_factor(T, Tsize, r, options, plot=False):
    # prepare options and dimensions
    maxiter, tol, maxiter_refine, tol_refine, init, trunc_dims, level, refine, symm, low, upp, factor, trials, display = aux.make_options(options)
    display = 3
    m, n, p = T.shape
    T, ordering = aux.sort_dims(T, m, n, p)
    m, n, p = T.shape
    N = 101

    if type(init) == list:
        print('Type of initialization: user')
    else:
        print('Type of initialization:', init)
    print()
     
    # compute compressed version of T   
    S, best_energy, R1, R2, R3, U1, U2, U3, sigma1, sigma2, sigma3, mlsvd_stop, best_error = tfx.mlsvd(T, Tsize, r, trunc_dims, level, display)

    # first run
    factors = np.linspace(0, 100, 100)
    errors = []
    i = 1
    print('First run')
    for factor in factors:
        X, Y, Z, rel_error = start_point(T, Tsize, S, U1, U2, U3, r, R1, R2, R3, init, ordering, symm, low, upp, factor, display) 
        errors.append(rel_error)
        # display progress bar
        s = "[" + i*"=" + (N-i-1)*" " + "]" + " " + str(i) + "%"
        sys.stdout.write('\r'+s)
        i += 1

    # second run    
    best_factor = factors[np.argmin(errors)]
    factors = np.linspace(best_factor-1, best_factor+1, 100)
    errors = []
    i = 1
    print('\nSecond run')
    for factor in factors:
        X, Y, Z, rel_error = start_point(T, Tsize, S, U1, U2, U3, r, R1, R2, R3, init, ordering, symm, low, upp, factor, display) 
        errors.append(rel_error)
        s = "[" + i*"=" + (N-i-1)*" " + "]" + " " + str(i) + "%"
        sys.stdout.write('\r'+s)
        i += 1
    
    # final result    
    best_factor = factors[np.argmin(errors)]
    best_error = errors[np.argmin(errors)]

    # plot factor x error curve if requested
    if plot:
        plt.plot(factors, errors, '+')
        plt.plot(best_factor, best_error, 'r*', label='Optimal factor')
        plt.xlabel('Factor')
        plt.ylabel('Relative error')
        plt.grid()
        plt.legend()
        plt.show()
    
    return best_factor, best_error
