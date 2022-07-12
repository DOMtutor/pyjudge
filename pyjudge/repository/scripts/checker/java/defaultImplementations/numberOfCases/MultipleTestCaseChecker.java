package defaultImplementations.numberOfCases;

import framework.CheckerInterface;

/**
 * Implementation of {@link framework.CheckerInterface#isSingularTestCase()}
 *
 * Use this if there are multiple test cases per file
 *
 * @author Philipp Hoffmann
 *
 */
public interface MultipleTestCaseChecker extends CheckerInterface {
	/**
	 * Always returns false. Use this if there are multiple test cases per file.
	 */
	default boolean isSingularTestCase() {
		return false;
	}
}
