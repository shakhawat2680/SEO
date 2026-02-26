from typing import List, Dict

class SEOAnalyzer:
    def analyze(self, pages: List[Dict]) -> Dict:
        """Analyze all pages and return results"""
        issues = []
        total_score = 0
        
        for page in pages:
            page_issues = self._analyze_page(page)
            issues.extend(page_issues)
            page_score = 100 - (len(page_issues) * 5)
            total_score += max(0, page_score)
        
        avg_score = total_score / len(pages) if pages else 0
        
        return {
            'score': round(avg_score, 2),
            'issues': self._summarize_issues(issues),
            'pages_analyzed': len(pages)
        }
    
    def _analyze_page(self, page: Dict) -> List[Dict]:
        """Analyze single page"""
        issues = []
        
        # Title checks
        if not page['title']:
            issues.append({
                'type': 'missing_title',
                'page': page['url'],
                'priority': 'high',
                'description': 'Page title is missing',
                'suggestion': 'Add a unique title tag (50-60 characters)'
            })
        elif len(page['title']) < 30:
            issues.append({
                'type': 'title_too_short',
                'page': page['url'],
                'priority': 'medium',
                'description': f'Title too short ({len(page["title"])} chars)',
                'suggestion': 'Increase title to 50-60 characters'
            })
        elif len(page['title']) > 70:
            issues.append({
                'type': 'title_too_long',
                'page': page['url'],
                'priority': 'medium',
                'description': f'Title too long ({len(page["title"])} chars)',
                'suggestion': 'Reduce title to 50-60 characters'
            })
        
        # Meta description
        if not page['meta_description']:
            issues.append({
                'type': 'missing_description',
                'page': page['url'],
                'priority': 'high',
                'description': 'Meta description is missing',
                'suggestion': 'Add a compelling meta description (150-160 characters)'
            })
        
        # Headings
        if not page['h1']:
            issues.append({
                'type': 'missing_h1',
                'page': page['url'],
                'priority': 'high',
                'description': 'H1 heading is missing',
                'suggestion': 'Add one H1 heading that describes the page content'
            })
        elif len(page['h1']) > 1:
            issues.append({
                'type': 'multiple_h1',
                'page': page['url'],
                'priority': 'medium',
                'description': f'Multiple H1 tags found ({len(page["h1"])})',
                'suggestion': 'Use only one H1 heading per page'
            })
        
        # Images
        images_without_alt = [img for img in page['images'] if not img['alt']]
        if images_without_alt:
            issues.append({
                'type': 'missing_alt',
                'page': page['url'],
                'priority': 'medium',
                'description': f'{len(images_without_alt)} images missing alt text',
                'suggestion': 'Add descriptive alt text to all images'
            })
        
        # Content length
        if page['word_count'] < 300:
            issues.append({
                'type': 'thin_content',
                'page': page['url'],
                'priority': 'medium',
                'description': f'Low word count ({page["word_count"]} words)',
                'suggestion': 'Add more comprehensive content (aim for 500+ words)'
            })
        
        # Internal links
        internal_links = [l for l in page['links'] if l['internal']]
        if len(internal_links) < 3:
            issues.append({
                'type': 'few_internal_links',
                'page': page['url'],
                'priority': 'low',
                'description': f'Only {len(internal_links)} internal links',
                'suggestion': 'Add more internal links to improve site structure'
            })
        
        # Page speed
        if page['load_time'] > 3000:
            issues.append({
                'type': 'slow_page',
                'page': page['url'],
                'priority': 'high',
                'description': f'Slow load time ({page["load_time"]:.0f}ms)',
                'suggestion': 'Optimize images, enable caching, minify resources'
            })
        
        return issues
    
    def _summarize_issues(self, issues: List[Dict]) -> List[Dict]:
        """Summarize issues by type"""
        summary = {}
        for issue in issues:
            key = issue['type']
            if key not in summary:
                summary[key] = {
                    'type': issue['type'],
                    'priority': issue['priority'],
                    'description': issue['description'],
                    'suggestion': issue['suggestion'],
                    'pages': []
                }
            if issue['page'] not in summary[key]['pages']:
                summary[key]['pages'].append(issue['page'])
        
        for issue in summary.values():
            issue['count'] = len(issue['pages'])
            issue['pages'] = issue['pages'][:3]  # Show only first 3 examples
        
        return list(summary.values())
