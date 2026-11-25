# Data licenses

This file lists the datasets and models this playbook uses, where they come from, and their licenses. The code in this repository is MIT-licensed. That license does not cover third-party data or models; each one keeps its own license, listed below.

## Datasets

| Dataset | Source | License | In this repo |
|---|---|---|---|
| Healthcare Dataset (synthetic patient records; the names are generated) | [Kaggle: prasad22/healthcare-dataset](https://www.kaggle.com/datasets/prasad22/healthcare-dataset) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | `sample-data/healthcare_dataset.csv` (8 MB) |
| MHEALTH (body-worn sensor recordings) | [UCI Machine Learning Repository](https://archive.ics.uci.edu/dataset/319/mhealth+dataset), doi:10.24432/C5TW22 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | `sample-data/mhealth+dataset.zip` (72 MB) and `sample-data/MHEALTHDATASET/README.txt` (8 KB) |
| Barcode test images (6 PNGs) | Test images from the [ZXing](https://github.com/zxing/zxing) project | Apache-2.0 | `sample-data/bar-codes/` (444 KB) |
| `vtest.avi` video (768×576, 795 frames) | OpenCV [`samples/data`](https://github.com/opencv/opencv/tree/4.x/samples/data). Its resolution and length match the PETS 2009 sequence S2.L1 | Unclear (see Notes) | `sample-data/samples_data_vtest.avi` (7.8 MB) |
| Formulary (fictional medications mapped to four of the test barcodes) | Written for this playbook | MIT (this repository) | `sample-data/formulary.csv` (4 KB) |

No pretrained models are used.

## Notes

- `vtest.avi`: the license is unclear. The README says it is distributed with OpenCV (Apache-2.0), that OpenCV doesn't state its source, and that the PETS 2009 terms are unconfirmed.
- Two ZXing test images carry personal data: `datamatrix-1.png` (a name with an SSN-format number and dates) and `qrcode-1.png` (a contact card). The pipeline quarantines both and does not store or print their content.

## Citations

- MHEALTH: O. Banos, R. Garcia, J. A. Holgado-Terriza, M. Damas, H. Pomares, I. Rojas, A. Saez and C. Villalonga, "mHealthDroid: a novel framework for agile development of mobile health applications", *Proceedings of the 6th International Work-conference on Ambient Assisted Living an Active Ageing (IWAAL 2014)*, Belfast, United Kingdom, 2014.
- Healthcare Dataset, ZXing test images, `vtest.avi`: no citation given by the source.
