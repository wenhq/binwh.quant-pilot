# 准备工作

## 选择镜像

不同镜像支持的功能不同，参考[Selecting an Image](https://jupyter-docker-stacks.readthedocs.io/en/latest/using/selecting.html)。

- jupyter/base-notebook 只有notebook，lab等最基础的包
- jupyter/minimal-notebook 才有git等软件功能
- jupyter/datascience-notebook 包括了 jupyter/scipy-notebook，jupyter/r-notebook，jupyter/julia-notebook 等镜像的内容。其中 jupyter/scipy-notebook 镜像有 pandas、scipy、seaborn等常用库，以及 jupyterlab-git 功能。另外，考虑可能会继续学习r的相关支持，因此安装这个镜像。

## 安装语言包

在页面上执行
```shell
!pip install jupyterlab-language-pack-zh-CN
```

看到返回结果如下，表示成功。在阿里云的环境下多尝试几次总会成功的。
```text
Collecting jupyterlab-language-pack-zh-CN
  Using cached jupyterlab_language_pack_zh_cn-4.3.post2-py2.py3-none-any.whl.metadata (2.8 kB)
Downloading jupyterlab_language_pack_zh_cn-4.3.post2-py2.py3-none-any.whl (205 kB)
Installing collected packages: jupyterlab-language-pack-zh-CN
Successfully installed jupyterlab-language-pack-zh-CN-4.3.post2
```

安装成功后，使用 `ctrl + r` 刷新网页，在 **Settings** ➡️ **Language** 下选择 **Chinese** 调整语言。

![](https://static.binwh.com/img/2025/03/09/G0g3FY.png)

## 插件

-[] 待补充

## 其他库

-[] 待补充
