import torch
import copy,os
import numpy as np
import pickle as pkl
from .Bond import *
from .Bond import _fx_GetCommRows
from . import linalg

## Developer Note:
## [KHW]
## Currently trying to add the Symm.
## A temporary Abort is use to prevent the user to call the un-support operations on a Symmetry tensor.
##
##  Find "Qnum_ipoint" keyword for the part that need to be modify accrodingly when considering the Qnums feature.
##


class UniTensor():

    def __init__(self, bonds, N_inbond ,labels=None, device=torch.device("cpu"),dtype=torch.float64,torch_tensor=None,check=True, is_diag=False, is_blockform=False, requires_grad=False, name="", BlockInfo=None):
        """
        This is the constructor of the UniTensor.

        Public Args:

            bonds:
                The list of bonds. it should be an list or np.ndarray with len(list) is the # of bonds.

            N_inbond:
                The number of in-bond, The first [N_inbond] bonds will be define as the in-bond (the BD_IN in the uni10 definition) and the other bonds will be defined as the out-bond (the BD_OUT in the uni10 definition)
                When interprete the memory layout as Matrix, the combine of first N_inbond will be the row and the other bond will be column.


            labels:
                The label of each bond.
                1. the number of elements should be the same as the total rank of the tensor, contain no duplicated elements.
                2. all the label should be integer. if the label is specify as floating point, it will be rounded as integer.

            device:
                This should be a [torch.device]. When provided, the tensor will be put on the device ("cpu", "cuda", "cuda:x" with x is the GPU-id. See torch.device for further information.)

            dtype :
                This should be a [ torch.dtype ].
                *The default type is float with either float32 or float64 which follows the same internal rule of pytorch. For further information, see pytorch documentation.

            is_diag:
                This states if the current UniTensor is a diagonal matrix or not. If True, the Storage will only store diagonal elements.
                Note that if is_diag=True, then the UniTensor is strictly required to be a square rank-2 tensor.

            is_blockform:
                This states if the current UniTensor is in block-diagonalize form. If True, the Storage will be a list of 2D block.
                Note [1]: the sparse tensor can be either in blockform (is_blockform = True) or in diagonal form (is_diag = True) the two flag cannot coexists.
                Note [2]: When set to true, the order of qnums appear in each bond will be lexsort from large to small.


            requires_grad:
                Activate the autograd function for UniTensor. This is the same as torch.Tensor

            name:
                This states the name of current UniTensor.

        Private Args:


           ** [Warning] Private Args should not be call directly **


            torch_tensor :
                This is the internal arguments in current version. It should not be directly use, otherwise may cause inconsistence with Bonds and memory layout.
                    *For Developer:
                        > The torch_tensor should have the same rank as len(label), and with each bond dimensions strictly the same as describe as in bond in self.bonds.

            check :
                This is the internal arguments. It should not be directly use. If False, all the checking across bonds/labels/Storage.shape will be ignore.


        Example for how to create a UniTensor:

            * create a rank-2 UniTensor (matrix) with shape (3,4):
            >>> a = Tor10.UniTensor(bonds=[Tor10.Bond(3),Tor10.Bond(4)],N_inbond=1)

            * create a rank-3 UniTensor with one inbond and two outbond, shape (3,4,5) and set labels [-3,4,1] for each bond:
            >>> c = Tor10.UniTensor(bonds=[Tor10.Bond(3),Tor10.Bond(4),Tor10.Bond(5)],N_inbond=1,labels=[-3,4,1])

            * create a rank-2 UniTensor with one inbond, one outbond, shape (3,4) on GPU-0:
            >>> d = Tor10.UniTensor(bonds=[Tor10.Bond(3),Tor10.Bond(4)],N_inbond=1,device=torch.device("cuda:0"))

            * create a diagonal 6x6 rank-2 tensor(matrix):
              Note that if is_diag is True, N_inbond must be 1.
            >>> e = Tor10.UniTensor(bonds=[Tor10.Bond(6),Tor10.Bond(6)],N_inbond=1,is_diag=True)

            Note that when is_diag is set to True, the UniTensor should be a square matrix.

            * crate a rank-3 UniTensor with two in-bond and one-outbond, and single precision:
            >>> f = Tor10.UniTensor(bonds=[Tor10.Bond(3),Tor10.Bond(4),Tor10.Bond(5)],N_inbond=2,labels=[-3,4,1],dtype=torch.float32)



        """
        self.bonds = np.array(copy.deepcopy(bonds))
        self.N_inbond = int(N_inbond)
        self.name = name
        self.is_diag = is_diag
        self.is_blockform = is_blockform
        if BlockInfo is None:
            self._BlockMapper_in = None
            self._BlockMapper_out = None
            self._BlockQnums = None
        else:
            self._BlockMapper_in = copy.deepcopy(BlockInfo[0])
            self._BlockMapper_out = copy.deepcopy(BlockInfo[1])
            self._BlockQnums =copy.deepcopy(BlockInfo[2])



        if labels is None:
            self.labels = np.arange(len(self.bonds))
        else:
            self.labels = np.array(copy.deepcopy(labels),dtype=np.int)


        ## Checking:
        if check:
            ## check sparse flag coexists.
            if self.is_blockform and self.is_diag:
                raise Exception("UniTensor.__init__","the sparse Tensor can be either is_blockform=True or is_diag=True. not both.")

            ## check [N_inbond] valid.
            if len(self.bonds)>0:
                if N_inbond < 0 or N_inbond > len(self.bonds):
                    raise Exception("UniTensor.__init__","the N_inbond should be >=0 and < # of bonds")

            ## check # of labels consist with bond.
            if not len(self.labels) == (len(self.bonds)):
                raise Exception("UniTensor.__init__","labels size is not consistence with the rank")

            ## check duplicate label
            if not len(np.unique(self.labels)) == len(self.labels):
                raise Exception("UniTensor.__init__","labels contain duplicate element.")

            if is_diag:
                if not len(self.labels) == 2:
                    raise TypeError("UniTensor.__init__","is_diag=True require Tensor rank==2")

                if not self.N_inbond == 1:
                    raise TypeError("UniTensor.__init__","is_diag=True require Tensor rank==2, with 1 inbond and 1 outbond (N_inbond=1)")

                if not self.bonds[0].dim == self.bonds[1].dim:
                    raise TypeError("UniTensor.__init__","is_diag=True require Tensor to be square rank-2")

            elif is_blockform:
                if self.N_inbond < 1 or len(self.bonds)-self.N_inbond < 1:
                    raise TypeError("UniTensor.__init__","is_blockform=True must have at least one in-bond and one out-bond")

                if self.bonds[0].qnums is None:
                    raise TypeError("UniTensor.__init__","is_blockform=True must be symmetric Tensor with qnums.")



            if len(np.unique([ (bd.qnums is None) for bd in self.bonds])) != 1:
                raise TypeError("UniTensor.__init__","the bonds are not consistent. Cannot have mixing bonds of with and without symmetry (qnums).")

            if self.bonds[0].qnums is not None:
                if len(np.unique([ bd.nsym for bd in self.bonds])) != 1:
                    raise TypeError("UniTensor.__init__","the number of symmetry type for symmetry bonds doesn't match.")


        if torch_tensor is None:
            if self.is_diag:
                self.Storage = torch.zeros(self.bonds[0].dim,device=device,dtype=dtype)

            elif self.is_blockform:

                ## sort for each bonds qnums:
                for bd in range(len(self.bonds)):
                    y = np.lexsort(self.bonds[bd].qnums.T[::-1])[::-1]
                    self.bonds[bd].qnums = self.bonds[bd].qnums[y,:]

                ## Get common qnums for in and out bond
                b_tqin,b_tqout = self.GetTotalQnums()
                tqin_uni = b_tqin.GetUniqueQnums()
                tqout_uni= b_tqout.GetUniqueQnums()
                C = _fx_GetCommRows(tqin_uni, tqout_uni)
                if len(C.flatten())==0:
                    raise TypeError("UniTensor.__init__","[ERROR] no valid block in current Tensor. please check in-qnums and out-qnums have at least one same set of qnums.")


                #Create block:
                self.Storage = []
                self._BlockMapper_in = []
                self._BlockMapper_out = []
                self._BlockQnums = []
                for blk in range(len(C)):
                    comm = tuple(C[blk])
                    idx_in= np.where((b_tqin.qnums == tuple(C[blk])).all(axis=1))[0]
                    idx_out= np.where((b_tqout.qnums == tuple(C[blk])).all(axis=1))[0]
                    self.Storage.append(torch.zeros((len(idx_in),len(idx_out)),device=device,dtype=dtype))
                    self._BlockMapper_in.append(idx_in)
                    self._BlockMapper_out.append(idx_out)
                    self._BlockQnums.append(C[blk])
                self._BlockQnums = np.array(self._BlockQnums)

            else:
                DALL = [self.bonds[i].dim for i in range(len(self.bonds))]
                self.Storage = torch.zeros(tuple(DALL), device=device, dtype = dtype)
                del DALL

        else:
            self.Storage = torch_tensor

        if requires_grad:
            self.Storage.requires_grad_(True)


    def SetLabel(self, newLabel, idx):
        """
        Set a new label for the bond local at specify index.

        Args:

            newLabel: The new label, it should be an integer.

            idx     : The index of the bond. when specified, the label of the bond at this index will be changed.

        Example:

            >>> g = Tor10.UniTensor(bonds=[Tor10.Bond(3),Tor10.Bond(4)],N_inbond=1,labels=[5,6])
            >>> g.labels
            [5 6]


            Set "-1" to replace the original label "6" at index 1

            >>> g.SetLabel(-1,1)
            >>> g.labels
            [5 -1]

        """
        if not type(newLabel) is int or not type(idx) is int:
            raise TypeError("UniTensor.SetLabel","newLabel and idx must be int.")

        if not idx < len(self.labels):
            raise ValueError("UniTensor.SetLabel","idx exceed the number of bonds.")

        if newLabel in self.labels:
            raise ValueError("UniTensor.SetLabel","newLabel [%d] already exists in the current UniTensor."%(newLabel))

        self.labels[idx] = newLabel

    def SetLabels(self,newlabels):
        """
        Set new labels for all the bonds.

        Args:

            newLabels: The list of new label, it should be an python list or numpy array with size equal to the number of bonds of the UniTensor.

        Example:

            >>> g = Tor10.UniTensor(bonds=[Tor10.Bond(3),Tor10.Bond(4)],N_inbond=1,labels=[5,6])
            >>> g.labels
            [5 6]

            Set new_label=[-1,-2] to replace the original label [5,6].

            >>> new_label=[-1,-2]
            >>> g.SetLabels(new_label)
            >>> g.labels
            [-1 -2]

        """
        if isinstance(newlabels,list):
            newlabels = np.array(newlabels)

        if not len(newlabels) == len(self.labels):
            raise ValueError("UniTensor.SetLabels","the length of newlabels not match with the rank of UniTensor")

        if len(np.unique(newlabels)) != len(newlabels):
            raise ValueError("UniTensor.SetLabels","the newlabels contain duplicated elementes.")

        self.labels = copy.copy(newlabels)

    def SetElem(self, elem):
        """
        Given 1D array of elements, set the elements stored in tensor as the same as the given ones. Note that elem can only be python-list or numpy

        Args:

            elem:
                The elements to be replace the content of the current UniTensor. It should be a 1D array.
                **Note** if the UniTensor is a symmetric tensor, one should use UniTensor.PutBlock to set the elements.

        Example:
        ::
            Sz = Tor10.UniTensor(bonds=[Tor10.Bond(2),Tor10.Bond(2)],N_inbond=1,
                              dtype=torch.float64,
                              device=torch.device("cpu"))
            Sz.SetElem([1, 0,
                        0,-1 ])


        >>> print(Sz)
        Tensor name:
        is_diag    : False
        tensor([[ 1.,  0.],
                [ 0., -1.]], dtype=torch.float64)

        """
        if not isinstance(elem,list) and not isinstance(elem,np.ndarray):
            raise TypeError("UniTensor.SetElem","[ERROR]  elem can only be python-list or numpy")

        if not len(elem) == self.Storage.numel():
            raise ValueError("UniTensor.SetElem","[ERROR] number of elem is not equal to the # of elem in the tensor.")

        ## Qnum_ipoint [OK]
        if self.bonds[0].qnums is not None:
            raise Exception("UniTensor.SetElem","[ERROR] the TN that has symm should use PutBlock.")

        my_type = self.Storage.dtype
        my_shape = self.Storage.shape
        my_device = self.Storage.device
        self.Storage = torch.from_numpy(np.array(elem)).type(my_type).reshape(my_shape).to(my_device)

    def Todense(self):
        """
        Set the UniTensor to dense matrix.
            Currently only the diagonal matrix is stored as sparsed form. So it only has effect on UniTensor where is_diag = True

        Return:
            self

        Example:

            >>> a = Tor10.UniTensor(bonds=[Tor10.Bond(3),Tor10.Bond(3)],N_inbond=1,is_diag=True)
            >>> print(a.is_diag)
            True

            >>> print(a)
            Tensor name:
            is_diag    : True
            tensor([0., 0., 0.], dtype=torch.float64)

            >>> a.Todense()
            >>> print(a.is_diag)
            False

            >>> print(a)
            Tensor name:
            is_diag    : False
            tensor([[0., 0., 0.],
                    [0., 0., 0.],
                    [0., 0., 0.]], dtype=torch.float64)


        """
        if self.is_diag==True:
            self.Storage = torch.diag(self.Storage)
            self.is_diag=False
        elif self.is_blockform==True:
            print("developing.")
            exit(1)

        return self

    def to(self,device):
        """
        Set the UniTensor to device

        Args:

            device:
                This should be an [torch.device]
                torch.device("cpu") for put the tensor on host (cpu)
                torch.device("cuda:x") for put the tensor on GPU with index x

        Example:

            Construct a tensor (default is on cpu)

            >>> a = Tor10.UniTensor(bonds=[Tor10.Bond(3),Tor10.Bond(4)],N_inbond=1)

            Set to GPU.

            >>> a.to(torch.device("cuda:0"))


        """
        if not isinstance(device,torch.device):
            raise TypeError("[ERROR] UniTensor.to()","only support device argument in this version as torch.device")
        if self.is_blockform:
            for s in range(len(self.Storage)):
                self.Storage[s].to(device)
        else:
            self.Storage = self.Storage.to(device)

    ## print layout:
    def Print_diagram(self):
        """
        This is the beauty print of the tensor diagram. Including the information for the placeing device
        ::
            1.The left hand side is always the In-bond, and the right hand side is always the Out-bond.
            2.The number attach to the out-side of each leg is the Bond-dimension.
            3.The number attach to the in-side of each leg is the label.
            4.The real memory layout are follow clock-wise from upper-right to upper-left.


            [ex:] Rank = 4.
            shape: (1,2,3,6)
            N_inbond = 2
            labels=[0,5,3,11]

                        -----------
                   0  --| 1     3 |-- 3
                        |         |
                   5  --| 2     6 |-- 11
                        -----------

        """
        print("tensor Name : %s"%(self.name))
        print("tensor Rank : %d"%(len(self.labels)))
        if self.is_blockform:
            print("on device   : %s"%(self.Storage[0].device))
        else:
            print("on device   : %s"%(self.Storage.device))
        print("is_diag     : %s"%("True" if self.is_diag else "False"))

        #Nin = len([ 1 for i in range(len(self.labels)) if self.bonds[i].bondType is BD_IN])
        #Nout = len(self.labels) - Nin
        Nin = self.N_inbond
        Nout = len(self.bonds) - self.N_inbond
        if Nin > Nout:
            vl = Nin
        else:
            vl = Nout

        #print(vl)
        print("        ---------------     ")
        for i in range(vl):
            print("        |             |     ")
            if(i<Nin):
                l = "%3d __"%(self.labels[i])
                llbl = "%-3d"%(self.bonds[i].dim)
            else:
                l = "      "
                llbl = "   "
            if(i<Nout):
                r = "__ %-3d"%(self.labels[Nin+i])
                rlbl = "%3d"%(self.bonds[Nin+i].dim)
            else:
                r = "      "
                rlbl = "   "
            print("  %s| %s     %s |%s"%(l,llbl,rlbl,r))
        print("        |             |     ")
        print("        ---------------     ")

        for i in range(len(self.bonds)):
            print("lbl:%d "%(self.labels[i]),end="")
            print(self.bonds[i])




    def __str__(self):
        print("Tensor name: %s"%( self.name))
        print("is_diag    : %s"%("True" if self.is_diag else "False"))
        if self.is_blockform:
            for s in range(len(self.Storage)):
                print("----------------")
                print("Block Qnum = ",self._BlockQnums[s])
                print(self.Storage[s])
        else:
            print(self.Storage)

        return ""

    def __repr__(self):
        print("Tensor name: %s"%( self.name))
        print("is_diag    : %s"%("True" if self.is_diag else "False"))
        if self.is_blockform:
            for s in range(len(self.Storage)):
                print("----------------")
                print("Block Qnum = ",self._BlockQnums[s])
                print(self.Storage[s])
        else:
            print(self.Storage)

        return ""

    def __len__(self):
        return len(self.Storage)

    def __eq__(self,rhs):
        """
            Compare two UniTensor.
            ::
                a == b

            where a & b are UniTensors.

            Note that this will only compare the shape of Storage. Not the content of torch tensor.


        """
        if isinstance(rhs,self.__class__):
            iss = (self.is_diag == rhs.is_diag) and (self.is_blockform == rhs.is_blockform)

            iss = iss and (self.Storage.shape == rhs.Storage.shape) and (len(self.bonds) == len(rhs.bonds))
            if not iss:
                return False

            iss = iss and all(self.bonds[i]==rhs.bonds[i] for i in range(len(self.bonds))) and all(self.labels[i]==rhs.labels[i] for i in range(len(self.labels)))
            return iss

        else:
            raise ValueError("Bond.__eq__","[ERROR] invalid comparison between Bond object and other type class.")


    def shape(self):
        """
            Return the shape of UniTensor

            Return:
                torch.Size object, using np.array() or list() to convert to numpy array and python list.

        """
        if self.is_diag:
            return torch.Size([self.bonds[0].dim,self.bonds[0].dim])
        elif self.is_blockform:
            return torch.Size([self.bonds[x].dim for x in range(len(self.bonds))])
        else:
            return self.Storage.shape

    ## Fill :
    def __getitem__(self,key):
        if self.is_blockform:
            raise Exception("UniTensor.__getitem__","[ERROR] cannot use [] to getitem from a block-form tensor. Use get block first.")
        return self.Storage[key]

    def __setitem__(self,key,value):
        if self.is_blockform:
            raise Exception("UniTensor.__setitem__","[ERROR] cannot use [] to setitem from a block-form tensor. Use get block first.")

        self.Storage[key] = value


    ## Math ::
    def __add__(self,other):
        if isinstance(other, self.__class__):
            if self.is_blockform:
                if not other.is_blockform:
                    raise TypeError("UniTensor.+","[ERROR] cannot add a sparse block-form tensor with a densed tensor.")

                ## Check for matching:
                if len(self.Storage) != len(other.Storage):
                    raise TypeError("UniTensor.+","[ERROR] cannot add two sparse block-form tensors with different block-form.")


                b_tqin,b_tqout = self.GetTotalQnums()
                b_tqin_o,b_tqout_o = other.GetTotalQnums()
                if b_tqin != b_tqin_o or b_tqout != b_tqout_o:
                    raise TypeError("UniTensor.+","[ERROR] cannot add two sparse block-form tensors with different qnums.")

                tmp = UniTensor(bonds = self.bonds,\
                                labels=self.labels,\
                                N_inbond = self.N_inbond,\
                                is_blockform=True,\
                                BlockInfo = (self._BlockMapper_in,self._BlockMapper_out,self._BlockQnums),\
                                check=False,\
                                torch_tensor = [self.Storage[s] + other.Storage[s] for s in range(len(self.Storage))])

            else:
                if other.is_blockform:
                    raise TypeError("UniTensor.+","[ERROR] cannot add a dense tensor with sparse block-form tensor")

                if self.is_diag and other.is_diag:
                    tmp = UniTensor(bonds = self.bonds,\
                                    labels= self.labels,\
                                    N_inbond=self.N_inbond,\
                                    torch_tensor=self.Storage + other.Storage,\
                                    check=False,\
                                    is_diag=True)

                elif self.is_diag==False and other.is_diag==False:
                    tmp = UniTensor(bonds = self.bonds,\
                                    labels= self.labels,\
                                    N_inbond=self.N_inbond,\
                                    torch_tensor=self.Storage + other.Storage,\
                                    check=False)
                else:
                    if self.is_diag:
                        tmp = UniTensor(bonds = self.bonds,\
                                        labels= self.labels,\
                                        N_inbond=self.N_inbond,\
                                        torch_tensor=torch.diag(self.Storage) + other.Storage,\
                                        check=False)
                    else:
                        tmp = UniTensor(bonds = self.bonds,\
                                        labels= self.labels,\
                                        N_inbond=self.N_inbond,\
                                        torch_tensor=self.Storage + torch.diag(other.Storage),\
                                        check=False)
            return tmp
        else:
            if self.is_blockform:
                return UniTensor(bonds = self.bonds,\
                                 labels= self.labels,\
                                 N_inbond=self.N_inbond,\
                                 torch_tensor=[self.Storage[s] + other for s in range(len(self.Storage))],\
                                 BlockInfo = (self._BlockMapper_in,self._BlockMapper_out,self._BlockQnums),\
                                 check=False,
                                 is_blockform=True)
            else:
                return UniTensor(bonds = self.bonds,\
                                 labels= self.labels,\
                                 N_inbond=self.N_inbond,\
                                 torch_tensor=self.Storage + other,\
                                 check=False,
                                 is_diag=self.is_diag)

    def __sub__(self,other):
        if isinstance(other, self.__class__):
            if self.is_blockform:
                if not other.is_blockform:
                    raise TypeError("UniTensor.-","[ERROR] cannot sub a sparse block-form tensor with a densed tensor.")

                ## Check for matching:
                if len(self.Storage) != len(other.Storage):
                    raise TypeError("UniTensor.-","[ERROR] cannot sub two sparse block-form tensors with different block-form.")

                b_tqin,b_tqout = self.GetTotalQnums()
                b_tqin_o,b_tqout_o = other.GetTotalQnums()
                if b_tqin != b_tqin_o or b_tqout != b_tqout_o:
                    raise TypeError("UniTensor.-","[ERROR] cannot sub two sparse block-form tensors with different qnums.")

                tmp = UniTensor(bonds = self.bonds,\
                                labels=self.labels,\
                                N_inbond = self.N_inbond,\
                                is_blockform=True,\
                                BlockInfo = (self._BlockMapper_in,self._BlockMapper_out,self._BlockQnums),\
                                check=False,\
                                torch_tensor = [self.Storage[s] - other.Storage[s] for s in range(len(self.Storage))])

            else:
                if other.is_blockform:
                    raise TypeError("UniTensor.-","[ERROR] cannot sub a dense tensor with sparse block-form tensor")

                if self.is_diag and other.is_diag:
                    tmp = UniTensor(bonds = self.bonds,\
                                    labels= self.labels,\
                                    N_inbond=self.N_inbond,\
                                    torch_tensor=self.Storage - other.Storage,\
                                    check=False,\
                                    is_diag=True)

                elif self.is_diag==False and other.is_diag==False:
                    tmp = UniTensor(bonds = self.bonds,\
                                     labels= self.labels,\
                                     N_inbond=self.N_inbond,\
                                     torch_tensor=self.Storage - other.Storage,\
                                     check=False)
                else:
                    if self.is_diag:
                        tmp = UniTensor(bonds = self.bonds,\
                                        labels= self.labels,\
                                        N_inbond=self.N_inbond,\
                                        torch_tensor=torch.diag(self.Storage) - other.Storage,\
                                        check=False)
                    else:
                        tmp = UniTensor(bonds = self.bonds,\
                                        labels= self.labels,\
                                        N_inbond=self.N_inbond,\
                                        torch_tensor=self.Storage - torch.diag(other.Storage),\
                                        check=False)
            return tmp
        else :
            if self.is_blockform:
                return UniTensor(bonds = self.bonds,\
                                 labels= self.labels,\
                                 N_inbond=self.N_inbond,\
                                 torch_tensor=[self.Storage[s] - other for s in range(len(self.Storage))],\
                                 BlockInfo = (self._BlockMapper_in,self._BlockMapper_out,self._BlockQnums),\
                                 check=False,
                                 is_blockform=True)
            else:
                return UniTensor(bonds = self.bonds,\
                                 labels= self.labels,\
                                 N_inbond=self.N_inbond,\
                                 torch_tensor=self.Storage - other,\
                                 check=False,
                                 is_diag=self.is_diag)

    def __mul__(self,other):
        if isinstance(other, self.__class__):
            if self.is_blockform:
                if not other.is_blockform:
                    raise TypeError("UniTensor.*","[ERROR] cannot mul a sparse block-form tensor with a densed tensor.")

                ## Check for matching:
                if len(self.Storage) != len(other.Storage):
                    raise TypeError("UniTensor.*","[ERROR] cannot mul two sparse block-form tensors with different block-form.")

                b_tqin,b_tqout = self.GetTotalQnums()
                b_tqin_o,b_tqout_o = other.GetTotalQnums()
                if b_tqin != b_tqin_o or b_tqout != b_tqout_o:
                    raise TypeError("UniTensor.*","[ERROR] cannot mul two sparse block-form tensors with different qnums.")

                tmp = UniTensor(bonds = self.bonds,\
                                labels=self.labels,\
                                N_inbond = self.N_inbond,\
                                is_blockform=True,\
                                BlockInfo = (self._BlockMapper_in,self._BlockMapper_out,self._BlockQnums),\
                                check=False,\
                                torch_tensor = [self.Storage[s] * other.Storage[s] for s in range(len(self.Storage))])

            else:
                if other.is_blockform:
                    raise TypeError("UniTensor.*","[ERROR] cannot mul a dense tensor with sparse block-form tensor")

                if self.is_diag and other.is_diag:
                    tmp = UniTensor(bonds = self.bonds,\
                                    labels= self.labels,\
                                    N_inbond=self.N_inbond,\
                                    torch_tensor=self.Storage * other.Storage,\
                                    check=False,\
                                    is_diag=True)

                elif self.is_diag==False and other.is_diag==False:
                    tmp = UniTensor(bonds = self.bonds,\
                                     labels= self.labels,\
                                     N_inbond=self.N_inbond,\
                                     torch_tensor=self.Storage * other.Storage,\
                                     check=False)
                else:
                    if self.is_diag:
                        tmp = UniTensor(bonds = self.bonds,\
                                        labels= self.labels,\
                                        N_inbond=self.N_inbond,\
                                        torch_tensor=torch.diag(self.Storage) * other.Storage,\
                                        check=False)
                    else:
                        tmp = UniTensor(bonds = self.bonds,\
                                        labels= self.labels,\
                                        N_inbond=self.N_inbond,\
                                        torch_tensor=self.Storage * torch.diag(other.Storage),\
                                        check=False)
        else:
            if self.is_blockform:
                tmp = UniTensor(bonds = self.bonds,\
                                labels= self.labels,\
                                N_inbond=self.N_inbond,\
                                torch_tensor=[self.Storage[s] * other for s in range(len(self.Storage))],\
                                check=False,\
                                BlockInfo = (self._BlockMapper_in, self._BlockMapper_out, self._BlockQnums),\
                                is_blockform=True)
            else:
                tmp = UniTensor(bonds = self.bonds,\
                                labels= self.labels,\
                                N_inbond=self.N_inbond,\
                                torch_tensor=self.Storage * other,\
                                check=False,\
                                is_diag=self.is_diag)
        return tmp

    def __pow__(self,other):
        if self.is_blockform:
            return UniTensor(bonds=self.bonds,\
                             labels=self.labels,\
                             torch_tensor=[self.Storage[s]**other for s in range(len(self.Storage))],\
                             N_inbond=self.N_inbond,\
                             check=False,\
                             BlockInfo= (self._BlockMapper_in,self._BlockMapper_out,self._BlockQnums),\
                             is_blockform=True)
        else:
            return UniTensor(bonds=self.bonds,\
                             labels=self.labels,\
                             torch_tensor=self.Storage**other,\
                             N_inbond=self.N_inbond,\
                             check=False,\
                             is_diag=self.is_diag)


    def __truediv__(self,other):
        if isinstance(other, self.__class__):
            if self.is_blockform:
                if not other.is_blockform:
                    raise TypeError("UniTensor./","[ERROR] cannot truediv a sparse block-form tensor with a densed tensor.")

                ## Check for matching:
                if len(self.Storage) != len(other.Storage):
                    raise TypeError("UniTensor./","[ERROR] cannot truediv two sparse block-form tensors with different block-form.")

                b_tqin,b_tqout = self.GetTotalQnums()
                b_tqin_o,b_tqout_o = other.GetTotalQnums()
                if (b_tqin != b_tqin_o) or (b_tqout != b_tqout_o):
                    raise TypeError("UniTensor./","[ERROR] cannot truediv two sparse block-form tensors with different qnums.")

                tmp = UniTensor(bonds = self.bonds,\
                                labels=self.labels,\
                                N_inbond = self.N_inbond,\
                                is_blockform=True,\
                                BlockInfo = (self._BlockMapper_in,self._BlockMapper_out,self._BlockQnums),\
                                check=False,\
                                torch_tensor = [self.Storage[s] / other.Storage[s] for s in range(len(self.Storage))])

            else:
                if other.is_blockform:
                    raise TypeError("UniTensor./","[ERROR] cannot truediv a dense tensor with sparse block-form tensor")

                if self.is_diag:
                    if other.is_diag:
                        tmp =  UniTensor(bonds=self.bonds,\
                                         labels=self.labels,\
                                         N_inbond=self.N_inbond,\
                                         check=False,\
                                         torch_tensor=self.Storage / other.Storage,\
                                         is_diag=True)
                    else:
                        tmp =  UniTensor(bonds=self.bonds,\
                                         labels=self.labels,\
                                         N_inbond=self.N_inbond,\
                                         check=False,\
                                         torch_tensor=torch.diag(self.Storage) / other.Storage)

                else:
                    if other.is_diag:
                        tmp =  UniTensor(bonds=self.bonds,\
                                         labels=self.labels,\
                                         N_inbond=self.N_inbond,\
                                         check=False,\
                                         torch_tensor=self.Storage / torch.diag(other.Storage))
                    else:
                        tmp =  UniTensor(bonds=self.bonds,\
                                         labels=self.labels,\
                                         N_inbond=self.N_inbond,\
                                         check=False,\
                                         torch_tensor=self.Storage / other.Storage)

        else :
            if self.is_blockform:
                tmp = UniTensor(bonds=self.bonds,\
                                 labels=self.labels,\
                                 N_inbond=self.N_inbond,\
                                 check=False,\
                                 torch_tensor=[self.Storage[s] / other for s in range(len(self.Storage))],\
                                 BlockInfo = (self._BlockMapper_in,self._BlockMapper_out,self._BlockQnums),\
                                 is_blockform=True)

            else:
                tmp =  UniTensor(bonds=self.bonds,\
                                 labels=self.labels,\
                                 N_inbond=self.N_inbond,\
                                 check=False,\
                                 torch_tensor=self.Storage / other,\
                                 is_diag=self.is_diag)

        return tmp

    ## This is the same function that behaves as the memberfunction.
    def Svd(self):
        """
            This is the member function of Svd, see Tor10.linalg.Svd()
        """
        if self.is_blockform:
            raise Exception("UniTensor.Svd","[ERROR] cannot perform Svd on a sparse block-form tensor. use GetBlock() first and perform svd on the Block.")

        return linalg.Svd(self)

    #def Svd_truncate(self):
    #    """
    #        This is the member function of Svd_truncate, see Tor10.Svd_truncate()
    #    """
    #    return Svd_truncate(self)

    def Norm(self):
        """
            This is the member function of Norm, see Tor10.linalg.Norm
        """
        if self.is_blockform:
            raise Exception("UniTensor.Norm","[ERROR] cannot perform Norm on a sparse block-form tensor. use GetBlock() first and perform norm on the Block.")

        return linalg.Norm(self)

    def Det(self):
        """
            This is the member function of Det, see Tor10.linalg.Det
        """
        if self.is_blockform:
            raise Exception("UniTensor.Det","[ERROR] cannot perform Det on a sparse block-form tensor. use GetBlock() first and perform det on the Block.")

        return linalg.Det(self)

    def Matmul(self,b):
        """
            This is the member function of Matmul, see Tor10.linalg.Matmul
        """
        if self.is_blockform:
            raise Exception("UniTensor.Matmul","[ERROR] cannot perform MatMul on a sparse block-form tensor. use GetBlock() first and perform matmul on the Block.")

        return linalg.Matmul(self,b)


    ## Extended Assignment:
    def __iadd__(self,other):
        if isinstance(other, self.__class__):
            if self.is_blockform:
                if not other.is_blockform:
                    raise TypeError("UniTensor.+=","[ERROR] cannot += sparse block form tensor with dense tensor")
                for s in range(len(self.Storage)):
                    self.Storage[s] += other.Storage[s]

            else:
                if other.is_blockform:
                    raise TypeError("UniTensor.+=","[ERROR] cannot += dense tensor with sparse block form tensor.")

                if self.is_diag == other.is_diag:
                    self.Storage += other.Storage
                else:
                    if self.is_diag:
                        self.Storage = torch.diag(self.Storage) + other.Storage
                        self.is_diag=False
                    else:
                        self.Storage += torch.diag(other.Storage)

        else :
            if self.is_blockform:
                for s in range(len(self.Storage)):
                    self.Storage[s]+= other
            else:
                self.Storage += other

        return self

    def __isub__(self,other):
        if isinstance(other, self.__class__):
            if self.is_blockform:
                if not other.is_blockform:
                    raise TypeError("UniTensor.-=","[ERROR] cannot -= sparse block form tensor with dense tensor")
                for s in range(len(self.Storage)):
                    self.Storage[s] -= other.Storage[s]
            else:
                if other.is_blockform:
                    raise TypeError("UniTensor.-=","[ERROR] cannot -= dense tensor with sparse block form tensor.")
                if self.is_diag == other.is_diag:
                    self.Storage -= other.Storage
                else:
                    if self.is_diag:
                        self.Storage = torch.diag(self.Storage) + other.Storage
                        self.is_diag=False
                    else:
                        self.Storage -= torch.diag(other.Storage)

        else :
            if self.is_blockform:
                for s in range(len(self.Storage)):
                    self.Storage[s] -= other

            else:
                self.Storage -= other

        return self


    def __imul__(self,other):
        if isinstance(other, self.__class__):
            if self.is_blockform:
                if not other.is_blockform:
                    raise TypeError("UniTensor.*=","[ERROR] cannot *= sparse block-form tensor with dense tensor.")
                for s in range(len(self.Storage)):
                    self.Storage[s] *= other.Storage[s]

            else:
                if other.is_blockform:
                    raise TypeError("UniTensor.*=","[ERROR] cannot *= dense tensor with sparse block form tensor.")

                if self.is_diag == other.is_diag:
                    self.Storage *= other.Storage
                else:
                    if self.is_diag:
                        self.Storage = torch.diag(self.Storage) * other.Storage
                        self.is_diag=False
                    else:
                        self.Storage *= torch.diag(other.Storage)
        else :
            if self.is_blockform:
                for s in range(len(self.Storage)):
                    self.Storage[s] *= other
            else:
                self.Storage *= other

        return self


    ## Miscellaneous
    def Rand(self):
        """
        Randomize the UniTensor.

            Note that in current version, only a UniTensor without symmetry quantum numbers can be randomized.

        Return:
            self

        """
        if self.bonds[0].qnums is None:
            _Randomize(self)
        else:
            if self.is_blockform:
                _Randomize(self)
            else:
                ## Qnum_ipoint
                raise Exception("[Abort] UniTensor.Rand for dense symm TN is under developing")
        return self

    def CombineBonds(self,labels_to_combine,is_inbond=None,new_label=None):
        """
        This function combines the bonds in input UniTensor [a] by the specified labels [label].

        Args:

            labels_to_combine:
                labels that to be combined. It should be a int list / numpy array of the label. All the bonds with specified labels in the current UniTensor  will be combined

            is_inbond: [default=None]
                if is_inbond is set to None, the combined bond will becomes in- or out-bond accroding to the bond that has the largest INDEX.
                if is_inbond is set to True, the combined bond will becomes in-bond
                if is_inbond is set to False, the combined bond will becomes out-bond

            new_label [default=None]
                This should be an integer, for floating point number, it will be truncated to integer.

                if new_label is set to None, the combined bond will have label as the bond in the to-be-combined bond that has the largest INDEX in input tensor.
                if new_label is set, the combined bond will have label [new_label]

        Example:

            1. Combine Bond for an non-symmetric tensor.

            >>> bds_x = [Tor10.Bond(5),Tor10.Bond(5),Tor10.Bond(3)]
            >>> x = Tor10.UniTensor(bonds=bds_x, N_inbond=1, labels=[4,3,5])
            >>> y = Tor10.UniTensor(bonds=bds_x, N_inbond=1, labels=[4,3,5])
            >>> z = Tor10.UniTensor(bonds=bds_x, N_inbond=1, labels=[4,3,5])
            >>> x.Print_diagram()
            tensor Name :
            tensor Rank : 3
            on device   : cpu
            is_diag     : False
                    ---------------
                    |             |
                4 __| 5         5 |__ 3
                    |             |
                    |           3 |__ 5
                    |             |
                    ---------------
            lbl:4 Dim = 5 |
            REGULAR :
            _
            lbl:3 Dim = 5 |
            REGULAR :
            _
            lbl:5 Dim = 3 |
            REGULAR :

            [Note] Since is_inbond==None(default), so the combined bond will have label=3 and is an outbond, since the bond with label=3 has largest index appeard in input tensor.

            >>> x.CombineBonds([4,3])
            >>> x.Print_diagram()
            tensor Name :
            tensor Rank : 2
            on device   : cpu
            is_diag     : False
                    ---------------
                    |             |
                    |           3 |__ 5
                    |             |
                    |          25 |__ 3
                    |             |
                    ---------------
            lbl:5 Dim = 3 |
            REGULAR :
            _
            lbl:3 Dim = 25 |
            REGULAR :

            [Note] Since is_inbond==True, so the combined bond will force to be in-bond, but still have label=3 since the bond with label=3 has largest index appeard in input tensor.

            >>> y.CombineBonds([4,3],is_inbond=True)
            >>> y.Print_diagram()
            tensor Name :
            tensor Rank : 2
            on device   : cpu
            is_diag     : False
                    ---------------
                    |             |
                3 __| 25        3 |__ 5
                    |             |
                    ---------------
            lbl:3 Dim = 25 |
            REGULAR :
            _
            lbl:5 Dim = 3 |
            REGULAR :

            [Note] Since is_inbond==True and new_label is set, so the combined bond will force to be in-bond, and has label=8

            >>> z.CombineBonds([4,3],is_inbond=True,new_label=8)
            >>> z.Print_diagram()
            tensor Name :
            tensor Rank : 2
            on device   : cpu
            is_diag     : False
                    ---------------
                    |             |
                8 __| 25        3 |__ 5
                    |             |
                    ---------------
            lbl:8 Dim = 25 |
            REGULAR :
            _
            lbl:5 Dim = 3 |
            REGULAR :




        """
        if len(labels_to_combine)<2:
            raise ValueError("CombineBonds","[ERROR] the number of bond to combine should be >1")

        if self.is_blockform:
            print("developing")
            exit(1)

        _CombineBonds(self,labels_to_combine,is_inbond,new_label)

    def Contiguous(self):
        """
        Make the memory to be contiguous. This is the same as pytorch's contiguous().
        Because of the Permute does not move the memory, after permute, only the shape of UniTensor is changed, the underlying memory does not change. The UniTensor in this status is called "non-contiguous" tensor.
        When call the Contiguous(), the memory will be moved to match the shape of UniTensor.
        *Note* Normally, it is not nessary to call contiguous. Most of the linalg function implicity will make the UniTensor contiguous. If one calls a function that requires a contiguous tensor, the error will be issue. Then you know you have to put UniTensor.Contiguous() there.

        Return:
            self

        Example:

            >>> bds_x = [Tor10.Bond(5),Tor10.Bond(5),Tor10.Bond(3)]
            >>> x = Tt.UniTensor(bonds=bds_x,N_inbond=1, labels=[4,3,5])
            >>> print(x.is_contiguous())
            True

            >>> x.Permute([0,2,1],N_inbond=1)
            >>> print(x.is_contiguous())
            False

            >>> x.Contiguous()
            >>> print(x.is_contiguous())
            True

        """
        if self.is_blockform:
            print("developing")
            exit(1)
        else:
            self.Storage = self.Storage.contiguous()
        return self


    def is_contiguous(self):
        """
        Return the status of memory contiguous.

        Return:
            bool, if True, then the Storage of UniTensor is contiguous. if False, then the Storage of UiTensor is non-contiguous.

        """
        if self.is_blockform:
            print("developing")
            exit(1)
        else:
            return self.Storage.is_contiguous()


    def Permute(self,mapper,N_inbond,by_label=False):
        """
        Permute the bonds of the UniTensor.

        Args:
            mapper:
                a python list or 1d numpy array with integer type elements that the UniTensor permute accroding to.

            N_inbond:
                The number of in-bond after permute.

            by_label:
                bool, when True, the mapper using the labels. When False, the mapper using the index.

        Example:

            >>> bds_x = [Tor10.Bond(6),Tor10.Bond(5),Tor10.Bond(3)]
            >>> x = Tor10.UniTensor(bonds=bds_x, N_inbond=1,labels=[4,3,5])
            >>> y = Tor10.UniTensor(bonds=bds_x, N_inbond=1,labels=[4,3,5])
            >>> x.Print_diagram()
            tensor Name :
            tensor Rank : 3
            on device   : cpu
            is_diag     : False
                    ---------------
                    |             |
                4 __| 6         5 |__ 3
                    |             |
                    |           3 |__ 5
                    |             |
                    ---------------
            lbl:4 Dim = 6 |
            REGULAR :
            _
            lbl:3 Dim = 5 |
            REGULAR :
            _
            lbl:5 Dim = 3 |
            REGULAR :


            >>> x.Permute([0,2,1],N_inbond=2)
            >>> x.Print_diagram()
            tensor Name :
            tensor Rank : 3
            on device   : cpu
            is_diag     : False
                    ---------------
                    |             |
                4 __| 6         5 |__ 3
                    |             |
                5 __| 3           |
                    |             |
                    ---------------
            lbl:4 Dim = 6 |
            REGULAR :
            _
            lbl:5 Dim = 3 |
            REGULAR :
            _
            lbl:3 Dim = 5 |
            REGULAR :


            >>> y.Permute([3,4,5],N_inbond=2,by_label=True)
            >>> y.Print_diagram()
            tensor Name :
            tensor Rank : 3
            on device   : cpu
            is_diag     : False
                    ---------------
                    |             |
                3 __| 5         3 |__ 5
                    |             |
                4 __| 6           |
                    |             |
                    ---------------
            lbl:3 Dim = 5 |
            REGULAR :
            _
            lbl:4 Dim = 6 |
            REGULAR :
            _
            lbl:5 Dim = 3 |
            REGULAR :


        """
        if self.is_diag:
            raise Exception("UniTensor.Permute","[ERROR] UniTensor.is_diag=True cannot be permuted.\n"+
                                                "[Suggest] Call UniTensor.Todense()")

        elif self.is_blockform:
            print("developing")
            exit(1)


        if not (isinstance(mapper,list) or isinstance(mapper,np.ndarray)):
            raise TypeError("UniTensor.Permute","[ERROR] mapper should be an 1d python list or numpy array.")

        if by_label:
            ## check all label
            if not all(lbl in self.labels for lbl in mapper):
                raise Exception("UniTensor.Permute","[ERROR] by_label=True but mapper contain invalid labels not appear in the UniTensor label")

            DD = dict(zip(self.labels,np.arange(len(self.labels))))
            new_mapper=[ DD[x] for x in mapper]
            self.Storage = self.Storage.permute(new_mapper)
            self.labels = np.array(mapper)
            self.bonds = self.bonds[new_mapper]

        else:
            ## We don't need this. pytorch will handle the dimesion mismatch error.
            #if not len(mapper) == len(self.labels):
            #    raise ValueError("UniTensor.Permute", "[ERROR] len of mapper should be the same as the rank of the UniTensor.")

            self.Storage = self.Storage.permute(mapper)
            self.labels = self.labels[mapper]
            self.bonds = self.bonds[mapper]

        #for i in range(len(self.bonds)):
        #    if i < N_inbond:
        #        self.bonds[i].change(BD_IN)
        #    else:
        #        self.bonds[i].change(BD_OUT)
        self.N_inbond = N_inbond

    def Reshape(self,dimer,N_inbond,new_labels=None):
        """
        Reshape the UniTensor into the shape specified as [dimer], with the first [N_inbond] Bonds as in-bond and other bonds as out-bond.

        Args:

            dimer:
                The new shape of the UniTensor. This should be a python list.

            N_inbond:
                The number of in-bond.

            new_labels:
                The new labels that will be set for new bonds after reshape.

        Example:

            >>> bds_x = [Tor10.Bond(6),Tor10.Bond(5),Tor10.Bond(3)]
            >>> x = Tor10.UniTensor(bonds=bds_x, N_inbond=1,labels=[4,3,5])
            >>> x.Print_diagram()
            tensor Name :
            tensor Rank : 3
            on device   : cpu
            is_diag     : False
                    ---------------
                    |             |
                4 __| 6         5 |__ 3
                    |             |
                    |           3 |__ 5
                    |             |
                    ---------------
            lbl:4 Dim = 6 |
            REGULAR :
            _
            lbl:3 Dim = 5 |
            REGULAR :
            _
            lbl:5 Dim = 3 |
            REGULAR :


            >>> x.Reshape([2,3,5,3],new_labels=[1,2,3,-1],N_inbond=2)
            >>> x.Print_diagram()
            tensor Name :
            tensor Rank : 4
            on device   : cpu
            is_diag     : False
                    ---------------
                    |             |
                1 __| 2         5 |__ 3
                    |             |
                2 __| 3         3 |__ -1
                    |             |
                    ---------------
            lbl:1 Dim = 2 |
            REGULAR :
            _
            lbl:2 Dim = 3 |
            REGULAR :
            _
            lbl:3 Dim = 5 |
            REGULAR :
            _
            lbl:-1 Dim = 3 |
            REGULAR :



        """
        if self.is_diag:
            raise Exception("UniTensor.Reshape","[ERROR] UniTensor.is_diag=True cannot be Reshape.\n"+
                                                "[Suggest] Call UniTensor.Todense()")
        if not isinstance(dimer,list):
            raise TypeError("UniTensor.Reshape","[ERROR] mapper should be an python list.")

        ## Qnum_ipoint
        if self.bonds[0].qnums is not None:
            raise Exception("UniTensor.Reshape","[Abort] UniTensor with symm cannot be Reshape.\n")


        ## This is not contiguous
        self.Storage = self.Storage.view(dimer)
        if new_labels is None:
            self.labels = np.arange(len(dimer))
        else:
            self.labels  = np.array(new_labels)

        #f = lambda i,Nid,dim : Bond(BD_IN,dim) if i<Nid else Bond(BD_OUT,dim)
        #self.bonds  = np.array([f(i,N_inbond,dimer[i]) for i in range(len(dimer))])

        self.bonds = np.array([Bond(dimer[i]) for i in range(len(dimer))])
        self.N_inbond=N_inbond


    ## Symmetric Tensor function
    def GetTotalQnums(self):
        """
        Return two combined bond objects that has the information for the total qnums at in and out bonds.

        Return:
            qnums_inbonds, qnums_outbonds:

            qnums_inbonds:
                a Tor10.Bond, the combined in-bond

            qnums_outbonds:
                a Tor10.Bond, the combined out-bond.


        Example:

            * Multiple Symmetry::

                ## multiple Qnum:
                ## U1 x U1 x U1 x U1
                ## U1 = {-2,-1,0,1,2}
                ## U1 = {-1,1}
                ## U1 = {0,1,2,3}
                bd_sym_1 = Tor10.Bond(3,qnums=[[0, 2, 1, 0],
                                                     [1, 1,-1, 1],
                                                     [2,-1, 1, 0]])
                bd_sym_2 = Tor10.Bond(4,qnums=[[-1, 0,-1, 3],
                                                     [ 0, 0,-1, 2],
                                                     [ 1, 0, 1, 0],
                                                     [ 2,-2,-1, 1]])
                bd_sym_3 = Tor10.Bond(2,qnums=[[-1,-2,-1,2],
                                                      [ 1, 1, -2,3]])

                sym_T = Tor10.UniTensor(bonds=[bd_sym_1,bd_sym_2,bd_sym_3],N_inbond=2,labels=[1,2,3],dtype=torch.float64)

            >>> tqin, tqout = sym_T.GetTotalQnums()
            >>> print(tqin)
            Dim = 12 |
            REGULAR : U1::  -1 +0 +1 +2 +0 +1 +2 +3 +1 +2 +3 +4
                      U1::  +2 +2 +2 +0 +1 +1 +1 -1 -1 -1 -1 -3
                      U1::  +0 +0 +2 +0 -2 -2 +0 -2 +0 +0 +2 +0
                      U1::  +3 +2 +0 +1 +4 +3 +1 +2 +3 +2 +0 +1


            >>> print(tqout)
            Dim = 2 |
            REGULAR : U1::  -1 +1
                      U1::  -2 +1
                      U1::  -1 -2
                      U1::  +2 +3



        """
        if self.bonds[0].qnums is None:
            raise TypeError("UniTensor.GetTotalQnums","[ERROR] GetTotal Qnums from a non-symm tensor")

        if (self.N_inbond==0) or (self.N_inbond==len(self.bonds)):
            raise Exception("UniTensor.GetTotalQnums","[ERROR] The TN symmetry structure is incorrect, without either any in-bond or any-outbond")

        #virtual_cb-in
        cb_inbonds = copy.deepcopy(self.bonds[0])
        if self.N_inbond>1:
            cb_inbonds.combine(self.bonds[1:self.N_inbond])

        cb_outbonds = copy.deepcopy(self.bonds[self.N_inbond])
        if len(self.bonds)-self.N_inbond > 1:
            cb_outbonds.combine(self.bonds[self.N_inbond+1:])

        return cb_inbonds,cb_outbonds


    def PutBlock(self,block,*qnum):
        """
        """
        ## Note, block should be a numpy array.
        if self.bonds[0].qnums is None:
            raise Exception("[Warning] PutBlock cannot be use for non-symmetry TN. Use SetElem instead.")
        else:

            if len(qnum) != self.bonds[0].nsym :
                raise ValueError("UniTensor.PutBlock","[ERROR] The qnumtum numbers not match the number of type.")

            if self.is_diag:
                raise TypeError("UniTensor.PutBlock","[ERROR] Cannot put block on a diagonal tensor (is_diag=True)")

            if self.is_blockform:
                ## search if the tn has block of that qnums:

                iflag = False
                for s in range(len(self.Storage)):
                    if np.array(qnum) == self._BlockQnums[s]:
                        if isinstance(block,np.ndarray):
                            if torch.Size(np.shape(block)) != self.Storage[s].shape:
                                raise Exception("UniTensor.PutBlock","[ERROR] block size does not match")

                            self.Storage[s] = torch.from_numpy(block)#.to(torch.float64)

                        elif isinstance(block,self.Storage.__class__):
                            if self.Storage[s].shape != block.shape:
                                 raise Exception("UniTensor.PutBlock","[ERROR] block size does not match")
                            self.Storage[s] = block.clone()

                        elif isinstance(block,self.__class__):
                            if block.is_blockform:
                                raise Exception("UniTensor.PutBlock","[ERROR] cannot put a sparse block-from tensor")
                            if self.Storage[s].shape != block.Storage.shape:
                                raise Exception("UniTensor.PutBlock","[ERROR] block size does not match")

                            self.Storage[s] = block.Storage.clone()

                        else:
                            raise TypeError("UniTensor.PutBlock","[ERROR] the block can only be an np.array or a %s"%(self.Storage.__class__))
                        iflag = True
                        break

                if not iflag:
                    raise TypeError("UniTensor.PutBlock","[ERROR] No block has qnums:",qnum)


            else:

                ## create a copy of bonds and labels information that has all the BD_IN on first.
                # [IN, IN, ..., IN, IN, OUT, OUT, ..., OUT, OUT]
                #tmp = np.array([ (x.bondType is BD_OUT) for x in self.bonds])
                #mapper = np.argsort(tmp)
                #tmp_bonds = self.bonds[mapper]
                #tmp_labels = self.labels[mapper]
                #Nin = len(tmp[tmp==False])

                if (self.N_inbond==0) or (self.N_inbond==len(self.bonds)):
                    raise Exception("UniTensor.PutBlock","[ERROR] Trying to put a block on a TN without either any in-bond or any out-bond")

                #virtual_cb-in
                cb_inbonds = copy.deepcopy(self.bonds[0])
                if self.N_inbond > 1:
                    cb_inbonds.combine(self.bonds[1:self.N_inbond])

                i_in = np.argwhere(cb_inbonds.qnums[:,0]==qnum[0]).flatten()
                for n in np.arange(1,self.bonds[0].nsym,1):
                    i_in = np.intersect1d(i_in, np.argwhere(cb_inbonds.qnums[:,n]==qnum[n]).flatten())
                if len(i_in) == 0:
                    raise Exception("UniTensor.PutBlock","[ERROR] Trying to put a qnum block that is not exists in the total Qnum of in-bonds in current TN.")

                #virtual_cb_out
                cb_outbonds = copy.deepcopy(self.bonds[self.N_inbond])
                if len(self.bonds) - self.N_inbond > 1:
                    cb_outbonds.combine(self.bonds[self.N_inbond+1:])

                i_out = np.argwhere(cb_outbonds.qnums[:,0]==qnum[0]).flatten()
                for n in np.arange(1,self.bonds[0].nsym,1):
                    i_out = np.intersect1d(i_out, np.argwhere(cb_outbonds.qnums[:,n]==qnum[n]).flatten())
                if len(i_out) == 0:
                    raise Exception("UniTensor.PutBlock","[ERROR] Trying to put a qnum block that is not exists in the totoal Qnum out-bonds in current TN.")

                #rev_mapper = np.argsort(mapper)
                #self.Storage = self.Storage.permute(*mapper)
                ori_shape = self.Storage.shape
                print(self.Storage.shape)
                ## this will copy a new tensor , future can provide an shallow copy with no new tensor will create, using .view() possibly handy for Getblock and change the element inplace.
                self.Storage = self.Storage.reshape(np.prod(ori_shape[:self.N_inbond]),-1)
                print(self.Storage.shape)
                ## no need to check if the size match. if the size doesn't match, let torch handle the error.
                if isinstance(block,np.ndarray):
                    self.Storage[np.ix_(i_in,i_out)] = torch.from_numpy(block)#.to(torch.float64)
                elif isinstance(block,self.Storage.__class__):
                    self.Storage[np.ix_(i_in,i_out)] = block.clone()
                elif isinstance(block,self.__class__):
                    if block.is_blockform:
                        raise TypeError("UniTensor.PutBlock","[ERRROR] cannot put a sparse block-form tensor.")
                    self.Storage[np.ix_(i_in,i_out)] = block.Storage.clone()
                else:
                    raise TypeError("UniTensor.PutBlock","[ERROR] the block can only be an np.array or a %s"%(self.Storage.__class__))

                self.Storage = self.Storage.reshape(*ori_shape)#.permute(*rev_mapper)


    def GetBlock(self,*qnum):
        """
        Return the Block specify by the quantum number(s). If the UniTensor is non-symmetry, return self.

        Args:
            *qnum:
                The quantum number(s). Note that when get-block on a High-rank tensor, the quantum number represent the total quantum number of all the in(out)-bonds.

        Return:
            * UniTensor, rank-2 (for symmetry tensor)
            * self (only if the UniTensor is non-symmetry tensor)

        Example:
            * Single Symmetry::

                bd_sym_1 = Tor10.Bond(3,qnums=[[0],[1],[2]])
                bd_sym_2 = Tor10.Bond(4,qnums=[[-1],[2],[0],[2]])
                bd_sym_3 = Tor10.Bond(5,qnums=[[4],[2],[-1],[5],[1]])
                sym_T = Tor10.UniTensor(bonds=[bd_sym_1,bd_sym_2,bd_sym_3],N_inbond=2,labels=[10,11,12],dtype=torch.float64)

            >>> sym_T.Print_diagram()
            Tensor Name :
            tensor Rank : 3
            on device   : cpu
            is_diag     : False
                    ---------------
                    |             |
               10 __| 3         5 |__ 12
                    |             |
               11 __| 4           |
                    |             |
                    ---------------
            lbl:10 Dim = 3 |
            REGULAR : U1::  +0 +1 +2
            _
            lbl:11 Dim = 4 |
            REGULAR : U1::  -1 +2 +0 +2
            _
            lbl:12 Dim = 5 |
            REGULAR : U1::  +4 +2 -1 +5 +1

            >>> q_in, q_out = sym_T.GetTotalQnums()
            >>> print(q_in)
            Dim = 12 |
            REGULAR : U1::  -1 +2 +0 +2 +0 +3 +1 +3 +1 +4 +2 +4

            >>> print(q_out)
            Dim = 5 |
            REGULAR : U1::  +4 +2 -1 +5 +1

            >>> block_2 = sym_T.GetBlock(2)
            >>> print(block_2)
            Tensor name:
            is_diag    : False
            tensor([[0.],
                    [0.],
                    [0.]], dtype=torch.float64)


            * Multiple Symmetry::

                ## multiple Qnum:
                ## U1 x U1 x U1 x U1
                ## U1 = {-2,-1,0,1,2}
                ## U1 = {-1,1}
                ## U1 = {0,1,2,3}
                bd_sym_1 = Tor10.Bond(3,qnums=[[0, 2, 1, 0],
                                               [1, 1,-1, 1],
                                               [2,-1, 1, 0]])
                bd_sym_2 = Tor10.Bond(4,qnums=[[-1, 0,-1, 3],
                                               [ 0, 0,-1, 2],
                                               [ 1, 0, 1, 0],
                                               [ 2,-2,-1, 1]])
                bd_sym_3 = Tor10.Bond(2,qnums=[[-1,-2,-1,2],
                                               [ 1, 1, -2,3]])

                sym_T = Tor10.UniTensor(bonds=[bd_sym_1,bd_sym_2,bd_sym_3],N_inbond=2,labels=[1,2,3],dtype=torch.float64)

            >>> tqin, tqout = sym_T.GetTotalQnums()
            >>> print(tqin)
            Dim = 12 |
            IN  :U1::  -1 +0 +1 +2 +0 +1 +2 +3 +1 +2 +3 +4
                 U1::  +2 +2 +2 +0 +1 +1 +1 -1 -1 -1 -1 -3
                 U1::  +0 +0 +2 +0 -2 -2 +0 -2 +0 +0 +2 +0
                 U1::  +3 +2 +0 +1 +4 +3 +1 +2 +3 +2 +0 +1

            >>> print(tqout)
            Dim = 2 |
            OUT :U1::  -1 +1
                 U1::  -2 +1
                 U1::  -1 -2
                 U1::  +2 +3

            >>> block_1123 = sym_T.GetBlock(1,1,-2,3)
            >>> print(block_1123)
            Tensor name:
            is_diag    : False
            tensor([[0.]], dtype=torch.float64)

        """
        if self.is_diag:
            raise TypeError("UniTensor.GetBlock","[ERROR] Cannot get block on a diagonal tensor (is_diag=True)")


        if self.bonds[0].qnums is None:


            print("[Warning] GetBlock a non-symmetry TN will return self regardless of qnum parameter pass in.")
            return self

        else:
            if len(qnum) != self.bonds[0].nsym :
                raise ValueError("UniTensor.GetBlock","[ERROR] The qnumtum numbers not match the number of type.")

            if self.is_blockform:

                ## search if the tn has block of that qnums:
                for s in range(len(self.Storage)):
                    if np.array(qnum) == self._BlockQnums[s]:
                        return UniTensor(bonds=[Bond(dim=self.Storage[s].shape[0]),Bond(dim=self.Storage[s].shape[1])],\
                                         N_inbond = 1,\
                                         labels=[1,2],\
                                         torch_tensor=self.Storage[s].clone(),\
                                         check=False)

                ## if there is no block with qnum:
                raise TypeError("UniTensor.PutBlock","[ERROR] No block has qnums:",qnum)


            else:

                #######
                ## create a copy of bonds and labels information that has all the BD_IN on first.
                # [IN, IN, ..., IN, IN, OUT, OUT, ..., OUT, OUT]
                #tmp = np.array([ (x.bondType is BD_OUT) for x in self.bonds])
                #mapper = np.argsort(tmp)
                #tmp_bonds = self.bonds[mapper]
                #tmp_labels = self.labels[mapper]
                #Nin = len(tmp[tmp==False])

                if (self.N_inbond==0) or (self.N_inbond==len(self.bonds)):
                    raise Exception("UniTensor.GetBlock","[ERROR] Trying to get a block on a TN without either any in-bond or any out-bond")

                #virtual_cb-in
                cb_inbonds = copy.deepcopy(self.bonds[0])
                if self.N_inbond > 1:
                    cb_inbonds.combine(self.bonds[1:self.N_inbond])

                i_in = np.argwhere(cb_inbonds.qnums[:,0]==qnum[0]).flatten()
                for n in np.arange(1,self.bonds[0].nsym,1):
                    i_in = np.intersect1d(i_in, np.argwhere(cb_inbonds.qnums[:,n]==qnum[n]).flatten())
                if len(i_in) == 0:
                    raise Exception("UniTensor.GetBlock","[ERROR] Trying to get a qnum block that is not exists in the total Qnum of in-bonds in current TN.")

                #virtual_cb_out
                cb_outbonds = copy.deepcopy(self.bonds[self.N_inbond])
                if len(self.bonds) - self.N_inbond > 1:
                    cb_outbonds.combine(self.bonds[self.N_inbond+1:])

                i_out = np.argwhere(cb_outbonds.qnums[:,0]==qnum[0]).flatten()
                for n in np.arange(1,self.bonds[0].nsym,1):
                    i_out = np.intersect1d(i_out, np.argwhere(cb_outbonds.qnums[:,n]==qnum[n]).flatten())
                if len(i_out) == 0:
                    raise Exception("UniTensor.GetBlock","[ERROR] Trying to get a qnum block that is not exists in the totoal Qnum out-bonds in current TN.")

                ## virtual permute:
                #rev_mapper = np.argsort(mapper)
                #self.Storage = self.Storage.permute(*mapper)
                ori_shape = self.Storage.shape

                ## this will copy a new tensor , future can provide an shallow copy with no new tensor will create, using .view() possibly handy for Getblock and change the element inplace.
                out = self.Storage.reshape(np.prod(ori_shape[:self.N_inbond]),-1)[np.ix_(i_in,i_out)]

                #self.Storage = self.Storage.permute(*rev_mapper)

                #print(out)

                return UniTensor(bonds=[Bond(dim=out.shape[0]),Bond(dim=out.shape[1])],\
                                 N_inbond = 1,\
                                 labels=[1,2],\
                                 torch_tensor=out,\
                                 check=False)


    ## Autograd feature:
    def requires_grad(self,is_grad=None):
        """
        The status for the autograd property.

        Args:
            is_grad:
                bool, if the autograd mechanism should be activate on this UniTensor.
                If the argument is not set, it will return the current autograd status.

        Return:
            bool, return only when is_grad argument is ignored.

        Example:
        ::
            bds_x = [Tor10.Bond(5),Tor10.Bond(5),Tor10.Bond(3)]
            x = Tor10.UniTensor(bonds=bds_x, N_inbond=2, labels=[4,3,5])


        >>> print(x.requires_grad())
        False

        >>> x.requires_grad(True)
        >>> print(x.requires_grad())
        True

        >>> x.requires_grad(False)
        >>> print(x.requires_grad())
        False


        """
        if is_grad is None:
            if self.is_blockform:
                return self.Storage[0].requires_grad
            else:
                return self.Storage.requires_grad
        else:
            if self.is_blockform:
                for s in range(len(self.Storage)):
                    self.Storage[s].requires_grad_(bool(is_grad))
            else:
                self.Storage.requires_grad_(bool(is_grad))


    def grad(self):
        """
        Return the gradient tensors subject to x where x is the current UniTensor. The return is None by default and becomes a UniTensor the first time a call backward(). The future calls to backward() will accumulate (add) gradient into it.

        This is the same as torch.Tensor.grad


        :math:`d/dx`

        Return:
            UniTensor, the shape of the return UniTensor and it's bonds are the same as the original UniTensor, but with default labels.

        Example:

            >>> x = Tor10.UniTensor(bonds=[Tor10.Bond(2),Tor10.Bond(2)],N_inbond=1,requires_grad=True)
            >>> print(x)
            Tensor name:
            is_diag    : False
            tensor([[0., 0.],
                    [0., 0.]], dtype=torch.float64, requires_grad=True)

            >>> y = (x + 4)**2
            >>> print(y)
            Tensor name:
            is_diag    : False
            tensor([[16., 16.],
                    [16., 16.]], dtype=torch.float64, grad_fn=<PowBackward0>)

            >>> out = Tor10.Mean(y)
            >>> print(out)
            Tensor name:
            is_diag    : False
            tensor(16., dtype=torch.float64, grad_fn=<MeanBackward1>)

            >>> out.backward()
            >>> print(x.grad)
            Tensor name:
            is_diag    : False
            tensor([[2., 2.],
                    [2., 2.]], dtype=torch.float64)

        """
        if self.Storage.grad is None:
            return None
        else:
            if self.is_blockform:
                return UniTensor(bonds=copy.deepcopy(self.bonds),\
                                 N_inbond = self.N_inbond,\
                                 is_blockform = self.is_blockform,\
                                 BlockInfo = (self._BlockMapper_in, self._BlockMapper_out, self._BlockQnums),\
                                 torch_tensor=[self.Storage[s].grad for s in range(len(self.Storage))],\
                                 check=False)
            else:
                return UniTensor(bonds=copy.deepcopy(self.bonds),\
                                 N_inbond = self.N_inbond,\
                                 torch_tensor=self.Storage.grad,\
                                 check=False)

    def backward(self):
        """
        Backward the gradient flow in the contructed autograd graph. This is the same as torch.Tensor.backward
        """
        if self.is_blockform:
            for s in range(len(self.Storage)):
                self.Storage[s].backward()

        else:
            self.Storage.backward()


    def detach(self):
        """
        Detach the current tensor from the current graph, making it a leaf. This is the same as torch.Tensor.detach_()

        Return:
            self
        """
        if self.is_blockform:
            for s in range(len(self.Storage)):
                self.Storage[s].detach_()
        else:
            self.Storage.detach_()
        return self



###############################################################
#
# Action function
#
##############################################################
## I/O
def Save(a,filename):
    """
    Save a UniTensor to the file

    Args:
        a:
            The UniTensor that to be saved.

        filename:
            The saved file path

    Example:
    ::
        a = Tor10.UniTensor(bonds=[Tor10.Bond(3),Tor10.Bond(4)],N_inbond=1)
        Tor10.Save(a,"a.uniT")

    """
    if not isinstance(filename,str):
        raise TypeError("Save","[ERROR] Invalid filename.")
    if not isinstance(a,UniTensor):
        raise TypeError("Save","[ERROR] input must be the UniTensor")
    f = open(filename,"wb")
    pkl.dump(a,f)
    f.close()

def Load(filename):
    """
    Load a UniTensor from the file.

    Args:
        filename:
            The path of the file to be loaded

    Return:
        UniTensor

    Example:
    ::
        a = Tor10.Load("a.uniT")

    """
    if not isinstance(filename,str):
        raise TypeError("UniTensor.Save","[ERROR] Invalid filename.")
    if not os.path.exists(filename):
        raise Exception("UniTensor.Load","[ERROR] file not exists")

    f = open(filename,'rb')
    tmp = pkl.load(f)
    f.close()
    if not isinstance(tmp,UniTensor):
        raise TypeError("Load","[ERROR] loaded object is not the UniTensor")

    return tmp

def Contract(a,b):
    """
    Contract two tensors with the same labels.

    1. two tensors must be the same type, if "a" is a symmetry tensor, "b" must also be a symmetry tensor.
    2. When contract two symmetry tensor, the bonds that to be contracted must have the same qnums.

    Args:
        a:
            UniTensor

        b:
            UniTensor


    Return:
        UniTensor

    Example:
    ::
        x = Tor10.UniTensor(bonds=[Tor10.Bond(5),Tor10.Bond(5),Tor10.Bond(4)], N_inbond=2,labels=[4,3,5])
        y = Tor10.UniTensor(bonds=[Tor10.Bond(3),Tor10.Bond(4)],N_inbond=1,labels=[1,5])


    >>> x.Print_diagram()
    tensor Name :
    tensor Rank : 3
    on device   : cpu
    is_diag     : False
            ---------------
            |             |
        4 __| 5         4 |__ 5
            |             |
        3 __| 5           |
            |             |
            ---------------
    lbl:4 Dim = 5 |
    REGULAR :
    _
    lbl:3 Dim = 5 |
    REGULAR :
    _
    lbl:5 Dim = 4 |
    REGULAR :

    >>> y.Print_diagram()
    tensor Name :
    tensor Rank : 2
    on device   : cpu
    is_diag     : False
            ---------------
            |             |
        5 __| 4         3 |__ 1
            |             |
            ---------------
    lbl:5 Dim = 4 |
    REGULAR :
    _
    lbl:1 Dim = 3 |
    REGULAR :

    >>> c = Tt.Contract(x,y)
    >>> c.Print_diagram()
    tensor Name :
    tensor Rank : 3
    on device   : cpu
    is_diag     : False
            ---------------
            |             |
        4 __| 5         3 |__ 1
            |             |
        3 __| 5           |
            |             |
            ---------------
    lbl:4 Dim = 5 |
    REGULAR :
    _
    lbl:3 Dim = 5 |
    REGULAR :
    _
    lbl:1 Dim = 3 |
    REGULAR :

    """
    if isinstance(a,UniTensor) and isinstance(b,UniTensor):

        if a.is_blockform or b.is_blockform:
            print("contract for block form tensor is under developing.")
            exit(1)

        ## get same vector:
        same, a_ind, b_ind = np.intersect1d(a.labels,b.labels,return_indices=True)


        if(len(same)):

            ## Qnum_ipoint
            if (a.bonds[0].qnums is not None)^(b.bonds[0].qnums is not None):
                raise Exception("Contract(a,b)","[ERROR] contract Symm TN with non-sym tensor")

            if(a.bonds[0].qnums is not None):
                for i in range(len(a_ind)):
                    if not a.bonds[a_ind[i]].qnums.all() == b.bonds[b_ind[i]].qnums.all():
                        raise ValueError("Contact(a,b)","[ERROR] contract Bonds that has qnums mismatch.")

            aind_no_combine = np.setdiff1d(np.arange(len(a.labels)),a_ind)
            bind_no_combine = np.setdiff1d(np.arange(len(b.labels)),b_ind)

            if a.is_diag :
                tmpa = torch.diag(a.Storage).to(a.Storage.device)
            else:
                tmpa = a.Storage

            if b.is_diag :
                tmpb = torch.diag(b.Storage).to(b.Storage.device)
            else:
                tmpb = b.Storage

            tmp = torch.tensordot(tmpa,tmpb,dims=(a_ind.tolist(),b_ind.tolist()))

            new_bonds = np.concatenate([copy.deepcopy(a.bonds[aind_no_combine]),copy.deepcopy(b.bonds[bind_no_combine])])
            new_io = [ (aind_no_combine[x]>=a.N_inbond) for x in range(len(aind_no_combine))] + [(bind_no_combine[x]>=b.N_inbond)  for x in range(len(bind_no_combine))]
            new_labels = np.concatenate([copy.copy(a.labels[aind_no_combine]),copy.copy(b.labels[bind_no_combine])])

            new_io = np.array(new_io)
            #print(new_io)
            if len(new_bonds)>0:
                mapper = np.argsort(new_io)
                new_bonds = new_bonds[mapper]
                new_labels= new_labels[mapper]
                tmp = tmp.permute(*mapper)

            return UniTensor(bonds =new_bonds,\
                             labels=new_labels,\
                             N_inbond=len(np.argwhere(new_io==0)),\
                             torch_tensor=tmp,\
                             check=False)

        else:
            ## direct product

            if a.is_diag :
                tmpa = torch.diag(a.Storage)
            else:
                tmpa = a.Storage

            if b.is_diag :
                tmpb = torch.diag(b.Storage)
            else:
                tmpb = b.Storage

            tmp = torch.tensordot(tmpa,tmpb,dims=0)
            new_bonds = np.concatenate([copy.deepcopy(a.bonds),copy.deepcopy(b.bonds)])
            new_labels = np.concatenate([copy.copy(a.labels), copy.copy(b.labels)])
            new_io = [ (x>=a.N_inbond) for x in range(len(a.bonds))] + [(x>=b.N_inbond)  for x in range(len(b.bonds))]

            if len(new_bonds)>0:
                mapper = np.argsort(new_io)
                new_bonds = new_bonds[mapper]
                new_labels= new_labels[mapper]
                tmp = tmp.permute(*mapper)

            return UniTensor(bonds=new_bonds,\
                             labels=new_labels,\
                             N_inbond=a.N_inbond+b.N_inbond,\
                             torch_tensor=tmp,\
                             check=False)

    else:
        raise Exception('Contract(a,b)', "[ERROR] a and b both have to be UniTensor")


#def Contract_old(a,b):
#    """
#    """
#    if isinstance(a,UniTensor) and isinstance(b,UniTensor):
#
#
#        ## get same vector:
#        same, a_ind, b_ind = np.intersect1d(a.labels,b.labels,return_indices=True)
#
#        ## -v
#        #print(a_ind,b_ind)
#
#        if(len(same)):
#            ## check dim:
#            #for i in range(len(a_ind)):
#            #    if a.bonds[a_ind[i]].dim != b.bonds[b_ind[i]].dim:
#            #        raise ValueError("Contact(a,b)","[ERROR] contract Bonds that has different dim.")
#
#
#            ## Qnum_ipoint
#            if (a.bonds[0].qnums is not None)^(b.bonds[0].qnums is not None):
#                raise Exception("Contract(a,b)","[ERROR] contract Symm TN with non-sym tensor")
#
#            if(a.bonds[0].qnums is not None):
#                for i in range(len(a_ind)):
#                    if not a.bonds[a_ind[i]].qnums.all() == b.bonds[b_ind[i]].qnums.all():
#                        raise ValueError("Contact(a,b)","[ERROR] contract Bonds that has qnums mismatch.")
#
#            aind_no_combine = np.setdiff1d(np.arange(len(a.labels)),a_ind)
#            bind_no_combine = np.setdiff1d(np.arange(len(b.labels)),b_ind)
#
#            #print(aind_no_combine,bind_no_combine)
#
#            mapper_a = np.concatenate([aind_no_combine,a_ind])
#            mapper_b = np.concatenate([b_ind,bind_no_combine])
#
#            old_shape = np.array(a.Storage.shape) if a.is_diag==False else np.array([a.Storage.shape[0],a.Storage.shape[0]])
#            combined_dim = np.prod(old_shape[a_ind])
#
#            if a.is_diag :
#                tmpa = torch.diag(a.Storage).to(a.Storage.device)
#            else:
#                tmpa = a.Storage
#
#            if b.is_diag :
#                tmpb = torch.diag(b.Storage).to(b.Storage.device)
#            else:
#                tmpb = b.Storage
#
#            tmp = torch.matmul(tmpa.permute(mapper_a.tolist()).reshape(-1,combined_dim),\
#                               tmpb.permute(mapper_b.tolist()).reshape(combined_dim,-1))
#            new_shape = [ bd.dim for bd in a.bonds[aind_no_combine]] + [ bd.dim for bd in b.bonds[bind_no_combine]]
#            return UniTensor(bonds =np.concatenate([a.bonds[aind_no_combine],b.bonds[bind_no_combine]]),\
#                             labels=np.concatenate([a.labels[aind_no_combine],b.labels[bind_no_combine]]),\
#                             torch_tensor=tmp.view(new_shape),\
#                             check=False)
#
#        else:
#            ## direct product
#            Nin_a = len([1 for i in range(len(a.labels)) if a.bonds[i].bondType is BD_IN])
#            Nin_b = len([1 for i in range(len(b.labels)) if b.bonds[i].bondType is BD_IN])
#            Nout_a = len(a.labels) - Nin_a
#            Nout_b = len(b.labels) - Nin_b
#
#            new_label = np.concatenate([a.labels, b.labels])
#            DALL = [a.bonds[i].dim for i in range(len(a.bonds))] + [b.bonds[i].dim for i in range(len(b.bonds))]
#
#            mapper = np.concatenate([np.arange(Nin_a), len(a.labels) + np.arange(Nin_b), np.arange(Nout_a) + Nin_a, len(a.labels) + Nin_b + np.arange(Nout_b)])
#
#            if a.is_diag :
#                tmpa = torch.diag(a.Storage)
#            else:
#                tmpa = a.Storage
#
#            if b.is_diag :
#                tmpb = torch.diag(b.Storage)
#            else:
#                tmpb = b.Storage
#
#
#            return UniTensor(bonds=np.concatenate([a.bonds[:Nin_a],b.bonds[:Nin_b],a.bonds[Nin_a:],b.bonds[Nin_b:]]),\
#                            labels=np.concatenate([a.labels[:Nin_a], b.labels[:Nin_b], a.labels[Nin_a:], b.labels[Nin_b:]]),\
#                            torch_tensor=torch.ger(tmpa.view(-1),tmpb.view(-1)).reshape(DALL).permute(mapper.tolist()),\
#                            check=False)
#
#    else:
#        raise Exception('Contract(a,b)', "[ERROR] a and b both have to be UniTensor")





## The functions that start with "_" are the private functions

def _CombineBonds(a,label,is_inbond,new_label):
    """
    This function combines the bonds in input UniTensor [a] by the specified labels [label]. The bondType of the combined bonds will always follows the same bondType of bond in [a] with label of the largest index element in [label]

    Args:

        a:
            UniTensor

        label:

            labels that to be combined. It should be a int list / numpy array of the label. All the bonds with specified labels in the current UniTensor  will be combined

        is_inbond:
            the combined bond should be an inbond or not. If set, the combined bond will be an inbond.

    """
    if isinstance(a,UniTensor):
        if a.is_diag:
            raise TypeError("_CombineBonds","[ERROR] CombineBonds doesn't support diagonal matrix.")


        if a.is_blockform:
            print("developing.")
            exit(1)

        if len(label) > len(a.labels):
            raise ValueError("_CombineBonds","[ERROR] the # of label_to_combine should be <= rank of UniTensor")
        # checking :
        same_lbls, x_ind, y_ind = np.intersect1d(a.labels,label,return_indices=True)


        #print(x_ind)
        #print(y_ind)
        #print(same_lbls)
        if not len(same_lbls) == len(label):
            raise Exception("_CombineBonds","[ERROR], label_to_combine doesn't exists in the UniTensor")

        idx_no_combine = np.setdiff1d(np.arange(len(a.labels)),x_ind)
        old_shape = np.array(a.Storage.shape)

        combined_dim = old_shape[x_ind]
        combined_dim = np.prod(combined_dim)
        no_combine_dims = old_shape[idx_no_combine]

        if new_label is not None:
            newlbl = int(new_label)
            if newlbl in a.labels[idx_no_combine] or newlbl in a.labels[x_ind[1:]]:
                raise Exception("_CombineBonds","[ERROR], cannot set new_label to %d as there will be duplicate bond with this label after combined"%(newlbl))

            a.labels[x_ind[0]] = newlbl

        new_Nin = a.N_inbond
        #print(a.N_inbond)
        ## check if the combined bond will be in-bond or out-bond
        if x_ind[0]>=a.N_inbond:
        #if a.bonds[x_ind[0]].bondType is BD_OUT:
            for i in range(len(x_ind)-1):
                a.bonds[x_ind[0]].combine(a.bonds[x_ind[1+i]])
                new_Nin -= int(x_ind[1+i]<a.N_inbond)

            if is_inbond is True:
                new_Nin += 1 # this bond
                mapper = np.concatenate([x_ind,idx_no_combine])
                a.bonds = np.append(a.bonds[x_ind[0]],a.bonds[idx_no_combine])
                a.labels = np.append(a.labels[x_ind[0]],a.labels[idx_no_combine])
                a.Storage = a.Storage.permute(mapper.tolist()).contiguous().view(np.append(combined_dim,no_combine_dims).tolist())
            else:
                ## default
                mapper = np.concatenate([idx_no_combine,x_ind])
                a.bonds = np.append(a.bonds[idx_no_combine],a.bonds[x_ind[0]])
                a.labels = np.append(a.labels[idx_no_combine], a.labels[x_ind[0]])
                a.Storage = a.Storage.permute(mapper.tolist()).contiguous().view(np.append(no_combine_dims,combined_dim).tolist())

        else:
            for i in range(len(x_ind)-1):
                a.bonds[x_ind[0]].combine(a.bonds[x_ind[1+i]])
                new_Nin -= int(x_ind[1+i]<a.N_inbond)

            if is_inbond is False:
                new_Nin -= 1 # this bond
                mapper = np.concatenate([idx_no_combine,x_ind])
                a.bonds = np.append(a.bonds[idx_no_combine],a.bonds[x_ind[0]])
                a.labels = np.append(a.labels[idx_no_combine],a.labels[x_ind[0]])
                a.Storage = a.Storage.permute(mapper.tolist()).contiguous().view(np.append(no_combine_dims,combined_dim).tolist())
            else:
                ## default
                mapper = np.concatenate([x_ind,idx_no_combine])
                a.bonds = np.append(a.bonds[x_ind[0]],a.bonds[idx_no_combine])
                a.labels = np.append(a.labels[x_ind[0]],a.labels[idx_no_combine])
                a.Storage = a.Storage.permute(mapper.tolist()).contiguous().view(np.append(combined_dim,no_combine_dims).tolist())

        a.N_inbond=new_Nin



    else :
        raise Exception("_CombineBonds(UniTensor,int_arr)","[ERROR] )CombineBonds can only accept UniTensor")

def _Randomize(a):
    """
        @description: <private function> This function randomize a UniTensor.
        @params     :
                      a : UniTensor
        @return     : N/A

    """

    if isinstance(a,UniTensor):
        if a.is_blockform:
            for s in range(len(a.Storage)):
                a.Storage[s] = torch.rand(a.Storage[s].shape, dtype=a.Storage[s].dtype, device=a.Storage[s].device)
        else:
            a.Storage = torch.rand(a.Storage.shape, dtype=a.Storage.dtype, device=a.Storage.device)


    else:
        raise Exception("_Randomize(UniTensor)","[ERROR] _Randomize can only accept UniTensor")


def From_torch(torch_tensor,N_inbond,labels=None):
    """
    Construct UniTensor from torch.Tensor.

    If the input torch_tensor belongs to a autograd graph, the contructed UniTensor will preserve the role of the input torch_tensor in the computational graph.

    Args:
        torch_tensor:
            Torch.Tensor

        N_inbond:
            int, The number of inbond. Note that the first [N_inbond] bonds will be set to Tor10.BD_IN, and the remaining bonds will be set to Tor10.BD_OUT

        labels:
            python list or 1d numpy array, The labels for each bonds. If ignore, the constucted UniTensor will using the default labels for each bond.

    Return:
        UniTensor

    Example:

        >>> x = torch.ones(3,3)
        >>> print(x)
        tensor([[1., 1., 1.],
                [1., 1., 1.],
                [1., 1., 1.]])

        >>> y = Tor10.From_torch(x,N_inbond=1,labels=[4,5])
        >>> y.Print_diagram()
        tensor Name :
        tensor Rank : 2
        on device   : cpu
        is_diag     : False
                ---------------
                |             |
            4 __| 3         3 |__ 5
                |             |
                ---------------
        lbl:4 Dim = 3 |
        REGULAR :
        _
        lbl:5 Dim = 3 |
        REGULAR :


        >>> print(y)
        Tensor name:
        is_diag    : False
        tensor([[1., 1., 1.],
                [1., 1., 1.],
                [1., 1., 1.]])


        >>> x2 = torch.ones(3,4,requires_grad=True)
        >>> print(x2)
        tensor([[1., 1., 1., 1.],
                [1., 1., 1., 1.],
                [1., 1., 1., 1.]], requires_grad=True)

        >>> y2 = Tor10.From_torch(x2,N_inbond=1)
        >>> print(y2.requires_grad())
        True


    """
    if not isinstance(torch_tensor,torch.Tensor):
        raise TypeError("From_torch","[ERROR] can only accept torch.Tensor")

    shape = torch_tensor.shape

    if N_inbond > len(shape):
        raise ValueError("From_torch","[ERROR] N_inbond exceed the rank of input torch tensor.")

    new_bonds = [Bond(shape[i]) for i in range(N_inbond)]+\
                [Bond(shape[i]) for i in np.arange(N_inbond,len(shape),1)]


    return UniTensor(bonds=new_bonds,labels=labels,N_inbond=N_inbond,torch_tensor=torch_tensor)
