# -*- coding: utf-8 -*-
"""
    sphinx.builders.latex
    ~~~~~~~~~~~~~~~~~~~~~

    LaTeX builder.

    :copyright: Copyright 2007-2016 by the Sphinx team, see AUTHORS.
    :license: BSD, see LICENSE for details.
"""

import os
from os import path
import warnings

from six import iteritems
from docutils import nodes
from docutils.io import FileOutput
from docutils.utils import new_document
from docutils.frontend import OptionParser

from sphinx import package_dir, addnodes, highlighting
from sphinx.util import texescape
from sphinx.config import string_classes
from sphinx.errors import SphinxError
from sphinx.locale import _
from sphinx.builders import Builder
from sphinx.environment import NoUri
from sphinx.util.nodes import inline_all_toctrees
from sphinx.util.osutil import SEP, copyfile, make_filename
from sphinx.util.console import bold, darkgreen
from sphinx.writers.latex import LaTeXWriter


class LaTeXBuilder(Builder):
    """
    Builds LaTeX output to create PDF.
    """
    name = 'latex'
    format = 'latex'
    supported_image_types = ['application/pdf', 'image/png', 'image/jpeg']
    usepackages = []

    def init(self):
        self.docnames = []
        self.document_data = []
        texescape.init()
        self.check_options()

    def check_options(self):
        if self.config.latex_toplevel_sectioning not in (None, 'part', 'chapter', 'section'):
            self.warn('invalid latex_toplevel_sectioning, ignored: %s' %
                      self.config.latex_toplevel_sectioning)
            self.config.latex_toplevel_sectioning = None

        if self.config.latex_use_parts:
            warnings.warn('latex_use_parts will be removed at Sphinx-1.5. '
                          'Use latex_toplevel_sectioning instead.',
                          DeprecationWarning)

            if self.config.latex_toplevel_sectioning:
                self.warn('latex_use_parts conflicts with latex_toplevel_sectioning, ignored.')

    def get_outdated_docs(self):
        return 'all documents'  # for now

    def get_target_uri(self, docname, typ=None):
        if docname not in self.docnames:
            raise NoUri
        else:
            return '%' + docname

    def get_relative_uri(self, from_, to, typ=None):
        # ignore source path
        return self.get_target_uri(to, typ)

    def init_document_data(self):
        preliminary_document_data = [list(x) for x in self.config.latex_documents]
        if not preliminary_document_data:
            self.warn('no "latex_documents" config value found; no documents '
                      'will be written')
            return
        # assign subdirs to titles
        self.titles = []
        for entry in preliminary_document_data:
            docname = entry[0]
            if docname not in self.env.all_docs:
                self.warn('"latex_documents" config value references unknown '
                          'document %s' % docname)
                continue
            self.document_data.append(entry)
            if docname.endswith(SEP+'index'):
                docname = docname[:-5]
            self.titles.append((docname, entry[2]))

    def write_stylesheet(self):
        highlighter = highlighting.PygmentsBridge(
            'latex', self.config.pygments_style, self.config.trim_doctest_flags)
        stylesheet = path.join(self.outdir, 'sphinxhighlight.sty')
        with open(stylesheet, 'w') as f:
            f.write('\\NeedsTeXFormat{LaTeX2e}[1995/12/01]\n')
            f.write('\\ProvidesPackage{sphinxhighlight}'
                    '[2016/05/29 stylesheet for highlighting with pygments]\n\n')
            f.write(highlighter.get_stylesheet())

    def write(self, *ignored):
        docwriter = LaTeXWriter(self)
        docsettings = OptionParser(
            defaults=self.env.settings,
            components=(docwriter,),
            read_config_files=True).get_default_values()

        self.init_document_data()
        self.write_stylesheet()

        for entry in self.document_data:
            docname, targetname, title, author, docclass = entry[:5]
            toctree_only = False
            if len(entry) > 5:
                toctree_only = entry[5]
            destination = FileOutput(
                destination_path=path.join(self.outdir, targetname),
                encoding='utf-8')
            self.info("processing " + targetname + "... ", nonl=1)
            toctrees = self.env.get_doctree(docname).traverse(addnodes.toctree)
            if toctrees:
                if toctrees[0].get('maxdepth') > 0:
                    tocdepth = toctrees[0].get('maxdepth')
                else:
                    tocdepth = None
            else:
                tocdepth = None
            doctree = self.assemble_doctree(
                docname, toctree_only,
                appendices=((docclass != 'howto') and self.config.latex_appendices or []))
            doctree['tocdepth'] = tocdepth
            self.post_process_images(doctree)
            self.info("writing... ", nonl=1)
            doctree.settings = docsettings
            doctree.settings.author = author
            doctree.settings.title = title
            doctree.settings.contentsname = self.get_contentsname(docname)
            doctree.settings.docname = docname
            doctree.settings.docclass = docclass
            docwriter.write(doctree, destination)
            self.info("done")

    def get_contentsname(self, indexfile):
        tree = self.env.get_doctree(indexfile)
        contentsname = None
        for toctree in tree.traverse(addnodes.toctree):
            if 'caption' in toctree:
                contentsname = toctree['caption']
                break

        return contentsname

    def assemble_doctree(self, indexfile, toctree_only, appendices):
        self.docnames = set([indexfile] + appendices)
        self.info(darkgreen(indexfile) + " ", nonl=1)
        tree = self.env.get_doctree(indexfile)
        tree['docname'] = indexfile
        if toctree_only:
            # extract toctree nodes from the tree and put them in a
            # fresh document
            new_tree = new_document('<latex output>')
            new_sect = nodes.section()
            new_sect += nodes.title(u'<Set title in conf.py>',
                                    u'<Set title in conf.py>')
            new_tree += new_sect
            for node in tree.traverse(addnodes.toctree):
                new_sect += node
            tree = new_tree
        largetree = inline_all_toctrees(self, self.docnames, indexfile, tree,
                                        darkgreen, [indexfile])
        largetree['docname'] = indexfile
        for docname in appendices:
            appendix = self.env.get_doctree(docname)
            appendix['docname'] = docname
            largetree.append(appendix)
        self.info()
        self.info("resolving references...")
        self.env.resolve_references(largetree, indexfile, self)
        # resolve :ref:s to distant tex files -- we can't add a cross-reference,
        # but append the document name
        for pendingnode in largetree.traverse(addnodes.pending_xref):
            docname = pendingnode['refdocname']
            sectname = pendingnode['refsectname']
            newnodes = [nodes.emphasis(sectname, sectname)]
            for subdir, title in self.titles:
                if docname.startswith(subdir):
                    newnodes.append(nodes.Text(_(' (in '), _(' (in ')))
                    newnodes.append(nodes.emphasis(title, title))
                    newnodes.append(nodes.Text(')', ')'))
                    break
            else:
                pass
            pendingnode.replace_self(newnodes)
        return largetree

    def finish(self):
        # copy image files
        if self.images:
            self.info(bold('copying images...'), nonl=1)
            for src, dest in iteritems(self.images):
                self.info(' '+src, nonl=1)
                copyfile(path.join(self.srcdir, src),
                         path.join(self.outdir, dest))
            self.info()

        # copy TeX support files from texinputs
        self.info(bold('copying TeX support files...'))
        staticdirname = path.join(package_dir, 'texinputs')
        for filename in os.listdir(staticdirname):
            if not filename.startswith('.'):
                copyfile(path.join(staticdirname, filename),
                         path.join(self.outdir, filename))

        # copy additional files
        if self.config.latex_additional_files:
            self.info(bold('copying additional files...'), nonl=1)
            for filename in self.config.latex_additional_files:
                self.info(' '+filename, nonl=1)
                copyfile(path.join(self.confdir, filename),
                         path.join(self.outdir, path.basename(filename)))
            self.info()

        # the logo is handled differently
        if self.config.latex_logo:
            logobase = path.basename(self.config.latex_logo)
            logotarget = path.join(self.outdir, logobase)
            if not path.isfile(path.join(self.confdir, self.config.latex_logo)):
                raise SphinxError('logo file %r does not exist' % self.config.latex_logo)
            elif not path.isfile(logotarget):
                copyfile(path.join(self.confdir, self.config.latex_logo), logotarget)
        self.info('done')


def setup(app):
    app.add_builder(LaTeXBuilder)

    app.add_config_value('latex_documents',
                         lambda self: [(self.master_doc, make_filename(self.project) + '.tex',
                                        self.project, '', 'manual')],
                         None)
    app.add_config_value('latex_logo', None, None, string_classes)
    app.add_config_value('latex_appendices', [], None)
    app.add_config_value('latex_keep_old_macro_names', True, None)
    # now deprecated - use latex_toplevel_sectioning
    app.add_config_value('latex_use_parts', False, None)
    app.add_config_value('latex_toplevel_sectioning', None, None, [str])
    app.add_config_value('latex_use_modindex', True, None)  # deprecated
    app.add_config_value('latex_domain_indices', True, None, [list])
    app.add_config_value('latex_show_urls', 'no', None)
    app.add_config_value('latex_show_pagerefs', False, None)
    # paper_size and font_size are still separate values
    # so that you can give them easily on the command line
    app.add_config_value('latex_paper_size', 'letter', None)
    app.add_config_value('latex_font_size', '10pt', None)
    app.add_config_value('latex_elements', {}, None)
    app.add_config_value('latex_additional_files', [], None)
    app.add_config_value('latex_docclass', {}, None)
    # now deprecated - use latex_elements
    app.add_config_value('latex_preamble', '', None)
