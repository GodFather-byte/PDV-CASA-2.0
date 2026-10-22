# Componentes da interface Qt e do backup

O WillPDV continua proprietário. As bibliotecas de terceiros não passam a ser
proprietárias: prevalecem suas próprias licenças e direitos.

## Qt for Python / PySide6 Essentials e Shiboken6

Copyright The Qt Company Ltd. e demais contribuidores.
O aplicativo usa os módulos Qt Core, Gui e Widgets, distribuídos separadamente
como bibliotecas dinâmicas pelo PyInstaller no modo `onedir`.
Não incorpora Qt WebEngine nem utiliza módulos Qt exclusivamente comerciais.

A distribuição aberta de Qt for Python permite uso sob LGPLv3, sujeito ao
cumprimento dos seus termos. Não foi adquirida uma licença comercial Qt.
O uso proprietário do WillPDV não restringe os direitos concedidos pela LGPL
sobre as bibliotecas, inclusive a substituição por versões modificadas
compatíveis e a engenharia reversa necessária para depurar essas modificações.

Os textos completos LGPLv3 e GPLv3 acompanham o programa na pasta `licencas`.
Não alteramos as fontes dessas bibliotecas. As versões efetivamente usadas e
metadados/licenças fornecidos pelos pacotes ficam em
`licencas/DEPENDENCIAS.txt` e `licencas/pacotes` no programa distribuído.
Não trate a licença comercial que eventualmente acompanha os metadados do
fornecedor como a licença escolhida por este aplicativo.

Fontes e informações oficiais para obter e reconstruir as bibliotecas:

- PySide/Shiboken: <https://code.qt.io/cgit/pyside/pyside-setup.git/>
- Qt: <https://code.qt.io/cgit/qt/>
- Pacotes e versões: <https://pypi.org/project/PySide6-Essentials/>
- Obtenção de fontes: <https://download.qt.io/official_releases/>
- Termos e componentes: <https://doc.qt.io/qtforpython-6/licenses.html>
- Obrigações LGPL: <https://www.qt.io/licensing/open-source-lgpl-obligations>

Para redistribuição comercial, mantenha estes avisos e textos, o acesso às
fontes correspondentes às versões distribuídas e a possibilidade real de
substituir as bibliotecas. Revise também as licenças de componentes incluídos
pela versão do Qt utilizada. Esta nota técnica não substitui uma revisão
jurídica de conformidade.

## Cryptography

Copyright Python Cryptographic Authority e contribuidores.
Licença Apache-2.0 ou BSD-3-Clause, conforme metadados distribuídos.
As dependências nativas, incluindo OpenSSL, conservam seus próprios termos.

- Fontes: <https://github.com/pyca/cryptography>
- Licenças e contribuições: <https://cryptography.io/en/latest/limitations/>

O build copia os avisos de licença presentes nos metadados de cryptography,
cffi, PySide6 Essentials e Shiboken6 para junto do programa.

## Pillow (logotipos Tk e Qt)

A importação de imagens usa Pillow sob licença MIT-CMU, conforme os metadados distribuídos.
O build inclui seus avisos e os das bibliotecas de imagem fornecidas no pacote em
`licencas/pacotes/Pillow`. Fontes e licenças: <https://github.com/python-pillow/Pillow>.
